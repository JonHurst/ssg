import os
import sys
import shutil
import tomllib
import json
import re
import datetime
from pathlib import Path

from typing import NamedTuple, Any, Optional

import jinja2 as jinja
import imagesize  # type: ignore
import commonmark

VERSION = "0.1"


class Page(NamedTuple):
    id: str
    # output file
    path: Optional[str]
    dir: str
    filename: Optional[str]
    subdirs: list[str]
    # data
    content: dict[str, Any]
    data: dict[str, Any]
    # tags
    tags: list[str]
    # sibling processing
    weight: Optional[int]
    siblings: list[str] = []
    lighter: str | None = None
    heavier: str | None = None


class ImageInfo(NamedTuple):
    width: int
    height: int


class Task(NamedTuple):
    page_id: str
    latest_timestamp: int
    template: str
    output_path: Path


class Library(NamedTuple):
    pages: dict[str, Page]
    tasks: list[Task]
    versioned: dict[Path, int]
    image_info: dict[Path, ImageInfo]
    tags: dict[str, list[str]]


def status_message(msg: str) -> None:
    """Writes msg to stdout with a timestamp.

    :param msg: The message to write
    :returns: None
    """
    print(f"[{datetime.datetime.now().isoformat()}] {msg}", file=sys.stdout)


def error_message(msg: str, notes: list[str] = []) -> None:
    """Writes msg to stderr.

    :param msg: The message to write
    :returns: None:
    """
    print(f"[ERROR] {msg}", file=sys.stderr)
    for note in notes:
        print(f"        {note}", file=sys.stderr)


def find_site_root() -> Optional[Path]:
    """Find the directory that contains content and templates directories,
    starting at the current working directory and working upwards.

    :returns: The path of the directory or None if not found

    """
    p = Path.cwd()
    while p.name:
        if (p / "content").is_dir() and (p / "templates").is_dir():
            return p
        p = p.parent
    return None


def process_content(filepath: Path) -> Any:
    '''Process a toml, json, or generic text file.

    TOML files are identified by a ".toml" suffix, and JSON files are
    identified by a ".json" suffix. If the content is TOML, it is simply handed
    to tomllib and the resulting dict returned. Similarly, JSON is passed to
    the json module and the resulting data structure is returned.

    If the file is neither TOML nor JSON, it is treated as a text file that may
    optionally be sharded. Sharded content is divided into sections by shard
    markers, which look like <!-- shard: myshard -->. A shard marker must be
    found as the first line of the file for the file to be treated as sharded.
    If the file is not determined to be sharded, the contents of the file are
    simply returned as a string.

    Sharded content is effectively an alternative way of writing TOML that
    contains only multiline text strings. A file with the contents:

    <!-- shard: a.b -->
    shard a.b 1
    <!-- shard: a.b -->
    shard a.b 2
    <!-- shard: c -->
    shard c

    converts to the TOML:

    a.b = ["""shard a.b 1""", """shard a.b 2"""]
    c = """shard c"""

    Note that where the same identifier is used multiple times, it binds the
    identifier to an array of multiline strings, wheras if the identifier is
    unique, it binds the identifier to a single multiline string. When
    processed by tomllib, this will return:

    {'a': {'b': ['shard a.b 1', 'shard a.b 2']},
     'c': 'shard c'}

    :param filepath: The path to a content file. TOML files should have ".toml"
        suffix and JSON files should have a ".json" suffix. A file with any
        other suffix is checked for a shard marker on the first line; if
        present, the file will be converted to TOML. If there is no shard
        marker, the file is treated as a generic text file.

    :return: For files with a ".toml" suffix, the result of passing the file
        content to tomllib.loads. For files with a ".json" suffix, the result
        of passing it to json.loads. For any other file, if sharded, the result
        of converting to TOML and then passing to tomllib.loads, otherwise the
        unprocessed text content of the file.

    :raises OSError: If filepath does not lead to a readable file

    :raises JSONDecodeError: If filepath has suffix ".json" but is not a valid
        JSON document.

    :raises UnicodeDecodeError: If filepath has suffix ".json" but does not
        contain UTF-8, UTF-16 or UTF-32 data.

    :raises TOMLDecodeError: If filepath has suffix ".toml" but does not
        contain valid TOML.

    '''
    try:
        content = filepath.read_text()
        if filepath.suffix == ".json":
            return json.loads(content)
        if filepath.suffix == ".toml":
            return tomllib.loads(content)
        shard_re = r"<!--\s*shard:\s*([\w.]+)\s*-->\s*$"
        shards = re.split(shard_re, content, flags=re.M)
        if len(shards) > 1 and shards[0] == "":  # Sharded content
            shard_dict: dict[str, list[str]] = {}
            for id_, shard in zip(shards[1::2], shards[2::2]):
                shard = shard.replace('"""', r'""\"').strip()
                shard_dict.setdefault(id_, []).append(shard)
            statements = []
            for k, v in shard_dict.items():
                if len(v) > 1:
                    array = ', '.join((f'"""{X}"""' for X in v))
                    statements.append(f"{k} = [{array}]")
                else:
                    statements.append(f'{k} = """{v[0]}"""')
            return tomllib.loads("\n".join(statements))
        return content  # Any other text content
    except (OSError, json.JSONDecodeError,
            UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        e.add_note(f"While processing {filepath}")
        raise e


def process_page_file(
        content_dir: Path, subdirs: list[Path], page_id: str
) -> tuple[Page, Optional[Task]]:
    """Load the .page file in the content_dir with page_id identifier, and
    extract all the attributes required to fill a Page structure. Also extract
    the name of the template to provide the Page structure to in order to
    create the output.

    :param content_dir: The directory containing the content of the website.
    :param subdirs: Directories in the same directory as page.
    :param page_id: The identifier of the page. This is the path from the
                    content directory to the file, with the ".page" extension
                    removed.
    :returns: The Page structure and the template.

    """
    status_message(f"Parsing {page_id}")
    page_path = (content_dir / page_id).with_suffix(".page")
    latest_timestamp = os.stat(page_path).st_mtime_ns
    with open(page_path, "rb") as f:
        toml = tomllib.load(f)
    content = {}
    try:
        for k, v in toml.get("content", {}).items():
            path = page_path.parent / v
            latest_timestamp = max(latest_timestamp, os.stat(path).st_mtime_ns)
            content[k] = process_content(path)
    except (AttributeError, FileNotFoundError):
        raise TypeError("Field 'content' must be a"
                        " TOML table of identifiers and valid filepaths.")
    data = toml.get("data", {})
    if "template" in toml:
        if not isinstance(toml["template"], str):
            raise TypeError("Field 'template' must be"
                            " a string giving a relative template path")
        suffix = toml.get("suffix", ".html")
        if not isinstance(suffix, str):
            raise TypeError("Field 'suffix' must be a string")
        path = Path(page_id).with_suffix(suffix)
        dir_ = path.parent.as_posix()
        name = path.name
        str_path = path.as_posix()
        task = Task(page_id, latest_timestamp, toml["template"], path)
    else:
        task = None
        dir_ = Path(page_id).parent.as_posix()
        str_path, name = "", ""
    tags = toml.get("tags", [])
    if ((not isinstance(tags, list)) or
            sum([not isinstance(X, str) for X in tags])):
        raise TypeError("Field 'tags' must be a list of strings")
    weight = process_weight(toml, page_id)
    page = Page(
        page_id,
        str_path, dir_, name, [X.as_posix() for X in subdirs],
        content, data, toml.get("tags", []), weight
    )
    return (page, task)


def process_weight(toml: dict[str, Any], page_id: str) -> None | int:
    """Extract the weight from the TOML of a page file.

    Weight defaults to 0 unless the page_id ends with 'index', in which case it
    defaults to None. To set it to None in the TOML requires the string "None"
    since TOML doesn't have a null type. It must be either an integer or None.

    :param toml: The TOML dict resulting from processing the page file
    :param page_id: The id of the page
    :result: The weight of the page

    """
    weight = toml.get("weight", None)
    if weight is None and not page_id.endswith("index"):
        weight = 0
    elif weight == "None":
        weight = None
    if not isinstance(weight, int | None):
        raise TypeError("Field 'weight' must be an"
                        " integer or the string \"None\"")
    return weight


def sort_siblings(
        siblings: set[str], me: str, pages: dict[str, Page]
) -> tuple[list[str], Optional[str], Optional[str]]:
    """Establish the relationship between pages in the same directory.

    :param siblings: A set of page identifiers to sort
    :param me: The page identifier to sort relative to
    :param pages: A dictionary of Page objects, keyed by their page identifier

    :returns: A tuple of three values. The first value is a list of pages
              ordered by weight then filename omitting the page identified by
              the me paramater. The second and third are the page identifier
              before me and the page identifier after me respectively.
    """

    def key(a):
        return (pages[a].weight, a)

    lighter, heavier = [], []
    if pages[me].weight is None:
        return (sorted(siblings, key=key), None, None)
    else:
        for s in siblings - {me}:
            if key(s) < key(me):
                lighter.append(s)
            else:
                heavier.append(s)
        lighter.sort(key=key)
        heavier.sort(key=key)
        return ((lighter + heavier),
                lighter[-1] if lighter else None,
                heavier[0] if heavier else None)


def fix_siblings(pages: dict[str, Page]) -> None:
    """Fill in sibling related fields for each page in pages. This function
    mutates pages, and so returns nothing.

    :param pages: A mapping of page_ids to Page objects.
    :returns: None. The pages dict is mutated.
    """
    dirnames = {K: os.path.dirname(K) for K in pages.keys()}
    # build sibling set lookup dict
    sibling_dict: dict[str, set] = {}
    for page_id in pages:
        if pages[page_id].weight is None or not pages[page_id].path:
            continue
        dir_ = dirnames[page_id]
        if dir_ not in sibling_dict:
            sibling_dict[dir_] = set()
        sibling_dict[dir_].add(page_id)
    # assign siblings
    for page_id in pages:
        dir_ = dirnames[page_id]
        if dir_ not in sibling_dict:
            continue
        siblings, lighter, heavier = sort_siblings(
            sibling_dict[dir_], page_id, pages)
        pages[page_id] = pages[page_id]._replace(
            siblings=siblings,
            lighter=lighter,
            heavier=heavier)


def build_library(content_dir: Path) -> Library:
    """Create a library containing the information needed to process the .page
    files into output files from the files in the content directory.

    :param content_dir: The path to the content directory.

    :returns: A library object with the following fields:

        pages: a Page object for every .page file, keyed by page identifier.
            The page identifier is the relative path from the content directory
            to the page file, minus the ".page" extension.

        templates: A dictionary linking page identifiers to the template that
            should be used to build the output file.

        versioned: A dictionary linking an unversioned filepath to the filepath
            with the highest version. For example if css/styles.1.css and
            css/styles.2.css both exist, css/styles.css will be the key and
            css.styles.2.css will be the value. Used by the 'latest' custom
            filter.

        image_info: A dictionary linking image urls to ImageInfo objects, which
            contain the width and height of the image. Used by the dimensions
            custom filter.

        tags: A dictionary linking tag strings to lists of page ids with those
            tags.
    """
    assert content_dir.is_dir()
    pages: dict[str, Page] = {}
    tasks: list[Task] = []
    image_info: dict[Path, ImageInfo] = {}
    max_version: dict[Path, int] = {}
    status_message("Building Library")
    for dirpath, dirnames, filenames in os.walk(content_dir):
        for f in filenames:
            filepath = Path(dirpath) / f
            relpath = filepath.relative_to(content_dir)
            # .page files
            if relpath.suffix == ".page":
                page_id = relpath.with_suffix("").as_posix()
                subdirs = [Path(X) for X in dirnames
                           if not Path(dirpath, X, ".ignore").exists()]
                try:
                    page, task = process_page_file(
                        content_dir, subdirs, page_id)
                except BaseException as e:
                    e.add_note(f"While processing {filepath}")
                    raise e
                if page:
                    pages[page_id] = page
                if task:
                    tasks.append(task)
                continue
            # image files for dimensions
            if relpath.suffix in (".jpeg", ".jpg", ".webp", ".png", ".gif"):
                image_info[relpath] = ImageInfo(*imagesize.get(filepath))
            # versioned files for max version mapping
            process_versioned(relpath, max_version)
    fix_siblings(pages)
    tags = process_tags(pages)
    status_message("Finished building library")
    return Library(pages, tasks, max_version, image_info, tags)


def process_tags(pages: dict[str, Page]) -> dict[str, list[str]]:
    """Extract a dictionary of which pageids contain which tags

    :param pages: A dictionary of Page objects
    :returns: A dictionary with tags as keys and a list of pageids containing
        those tags as values.
    """
    tags: dict[str, list[str]] = {}
    for v in pages.values():
        for tag in v.tags:
            tags.setdefault(tag, []).append(v.id)
    for k in tags:
        tags[k] = sorted(tags[k], key=lambda a: (pages[a].weight, a))
    return tags


def process_versioned(path: Path, max_version: dict[Path, int]) -> None:
    """Update max_version dict given a relative path.

    :param relpath: The path to check for versioning
    :param max_version: The dict recording latest versions of paths.
    :returns: None. The max_version param is mutated
    """
    try:
        version = int(path.suffixes[-2][1:])
        key = path.with_suffix("").with_suffix(path.suffix)
        if version > max_version.get(key, 0):
            max_version[key] = version
    except (ValueError, IndexError):
        pass  # not a versioned file


def define_jinja_filters(library: Library, env: jinja.Environment) -> None:
    """Add custom filters to Jinja environment.

    :param library: A Library object to supply data for filters.
    :param env: The Jinja environment to mutate.
    :return: This function mutates env, so returns None.
    """

    @jinja.pass_context
    def latest(context, s: str) -> str:
        """Transform an unversioned URL relative to the page into a versioned
        URL pointing at the latest version of the file. Versions are indicated
        by a numerical sub-suffix: css/styles.4.css is more recent than
        css/styles.3.css, so s would need to be css/styles.css to return
        css/styles.4.css.

        :param context: The Jinja context
        :param s: The URL to transform. This should be relative to the page.
        :return: The transformed URL, also relative to the page.

        """
        path = Path(s)
        # note: pathlib cannot normalize a relative path
        if path.root:
            key = Path(os.path.normpath(path.relative_to(path.root)))
        else:
            key = Path(os.path.normpath(Path(context["page"].dir, s)))
        if key in library.versioned:
            return str(path.with_suffix(
                f".{library.versioned[key]}{path.suffix}"))
        return s

    @jinja.pass_context
    def dimensions(context, s):
        key = Path(os.path.normpath(os.path.join(context["page"].dir, s)))
        if key in library.image_info:
            info = library.image_info[key]
            return {"width": info.width, "height": info.height}
        return {}

    def markdown(s: str) -> str:
        return commonmark.commonmark(s)

    env.filters["latest"] = latest
    env.filters["dimensions"] = dimensions
    env.filters["markdown"] = markdown


def output_site(
        templates: Path, library: Library, public: Path, quick: bool = False
) -> None:
    jinja_env = jinja.Environment(
        loader=jinja.FileSystemLoader(templates),
        trim_blocks=True, lstrip_blocks=True)
    define_jinja_filters(library, jinja_env)
    for task in library.tasks:
        if quick and (public / task.output_path).exists():
            ts = os.stat(public / task.output_path).st_mtime_ns
            if ts > task.latest_timestamp:
                continue
        status_message(f"Writing {task.page_id}")
        page = library.pages[task.page_id]
        template = jinja_env.get_template(task.template)
        root = ("/".join(".." for X in task.output_path.parent.parts) or
                ".") + "/"
        output = template.render(
            page=page, pages=library.pages, tags=library.tags, root=root)
        output_path = public / task.output_path
        old_output = output_path.exists() and output_path.read_text()
        if output != old_output:
            with open(public / task.output_path, "w") as f:
                f.write(output)
    status_message("Finished")


def build(content: Path, templates: Path, public: Path, quick: bool) -> None:
    """Build the site.

    Quick mode makes the often invalid assumption that the only files a .page
    file is dependent on are the .page file itself and files listed in its
    [content] directory. It should not be used if any change that is made to a
    .page file impacts other pages.

    :param content: The path to the content directory
    :param templates: The path to the templates directory
    :param public: The path to the output directory
    :param quick: Build in quick mode.

    """

    def ignore(dir_: str, filenames: list[str]) -> list[str]:
        ignore_list = []
        for f in filenames:
            path = Path(dir_, f)
            if path.suffix == ".page" or (path / ".ignore").exists():
                ignore_list.append(f)
            else:
                output_path = Path(public / path.relative_to(content))
                if output_path.exists():
                    mtime_content = os.stat(path).st_mtime_ns
                    mtime_public = os.stat(output_path).st_mtime_ns
                    if mtime_content < mtime_public:
                        ignore_list.append(f)
        return ignore_list

    status_message("Copying content to public")
    shutil.copytree(content, public, ignore=ignore, dirs_exist_ok=True)
    library = build_library(content)
    output_site(templates, library, public, quick)


def main() -> None:
    global VERSION
    print(f"ssg version {VERSION}\n")
    try:
        if not (site_root := find_site_root()):
            raise OSError("Could not find content directory")
        content, templates, public = (
            (site_root / X).resolve()
            for X in ("content", "templates", "public"))
        quick = len(sys.argv) > 1 and sys.argv[1] == "--quick"
        build(content, templates, public, quick)
        system_exit(0)
    except jinja.TemplateSyntaxError as e:
        error_message(
            f"Template Syntax Error at line {e.lineno} of {e.name}:\n"
            f"-- {e.message}\n-- Template called by {e.filename}")
        system_exit(-1)
    except (OSError, TypeError, UnicodeDecodeError,
            tomllib.TOMLDecodeError, json.JSONDecodeError,
            jinja.TemplateError) as e:
        error_message(str(e), e.__notes__)
        system_exit(-2)


def system_exit(code: int):
    if sys.platform == "win32":
        input("Press ENTER to exit")
    sys.exit(code)


if __name__ == "__main__":
    main()
