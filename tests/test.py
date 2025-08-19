import os.path
from pathlib import Path
import tomllib

from pyfakefs.fake_filesystem_unittest import (   # type: ignore
    TestCase as FFTestCase
)

from ssg.main import (
    Page,
    Task,
    Library,
    find_site_root,
    process_content,
    define_jinja_filters,
    build_library,
    output_site,
    build,)


def page_for_testing(page_path, **kwargs):
    path = Path(page_path)
    retval = Page(
        id=str(path.with_suffix("")),
        path=str(path.with_suffix(".html")),
        dir=str(path.parent),
        filename=(path.with_suffix(".html")).name,
        subdirs=[],
        content={},
        data={},
        weight=0,
        tags=[])
    return retval._replace(**kwargs)


class TestContentProcessing(FFTestCase):

    def setUp(self):
        self.setUpPyfakefs()

    def test_toml_processing(self):
        with open("/test.toml", "w") as f:
            f.write("simple = 'string'\n[table]\ntest = [1, 2, 3]\n")
        expected = {'simple': 'string', 'table': {'test': [1, 2, 3]}}
        self.assertEqual(
            process_content(Path("/test.toml")),
            expected)

    def test_json_processing(self):
        with open("/test.json", "w") as f:
            f.write('{"simple": "string", "table": {"test": [1, 2, 3]}}')
        expected = {'simple': 'string', 'table': {'test': [1, 2, 3]}}
        self.assertEqual(
            process_content(Path("/test.json")),
            expected)

    def test_simple_text_processing(self):
        with open("/test.html", "w") as f:
            f.write('<html></html>')
        self.assertEqual(
            process_content(Path("/test.html")),
            "<html></html>")

    def test_sharded_text_processing(self):
        with open("/test.md", "w") as f:
            f.write("\n".join(('<!-- shard: a.b -->',
                               'shard a.b.1',
                               '<!-- shard: a.b -->',
                               'shard a.b.2\nmore',
                               '<!-- shard: c -->',
                               'shard c')))
        expected = {'a': {'b': ['shard a.b.1', 'shard a.b.2\nmore']},
                    'c': 'shard c'}
        self.assertEqual(process_content(Path("/test.md")), expected)


class TestSSGMisc(FFTestCase):

    def setUp(self):
        self.setUpPyfakefs()

    def test_source_root_finding(self):
        os.makedirs("/root/site/content/lvl1/lvl2")
        os.makedirs("/root/site/templates/lvl1")
        # in root of source material
        os.chdir("/root/site")
        self.assertEqual(find_site_root(), Path("/root/site"))
        # deep in content
        os.chdir("/root/site/content/lvl1/lvl2")
        self.assertEqual(find_site_root(), Path("/root/site"))
        # in templates
        os.chdir("/root/site/templates/lvl1")
        self.assertEqual(find_site_root(), Path("/root/site"))
        # not in source tree
        os.chdir("/root")
        self.assertEqual(find_site_root(), None)


class TestLibraryBuild(FFTestCase):

    def setUp(self):
        self.setUpPyfakefs()

    def test_page_processing(self):
        os.makedirs("/content/subdir/subsubdir/hidden")
        with open("/content/test.page", "w") as f:
            f.write(
                "template = 'test'\n"
                "data.test = [1, 2, 3]\n"
                "content.main = 'test.html'\n")
        with open("/content/test.html", "w") as f:
            f.write("<p>Test</p>")
        with open("/content/subdir/subsubdir/index.page", "w") as f:
            f.write("")
        for n in range(3):
            with open(f"/content/subdir/subsubdir/sib_{n}.page", "w") as f:
                f.write(f"template = 'sib'\ntags=['tag{n}']\n")
        with open("/content/subdir/subsubdir/hidden/.ignore", "w") as f:
            f.write("")
        library = build_library(Path("/content"))
        self.assertEqual(
            library.pages["test"],
            page_for_testing(
                "test.page", subdirs=['subdir'],
                id='test',
                content={'main': '<p>Test</p>'},
                data={'test': [1, 2, 3]}))
        self.assertEqual(
            library.pages["subdir/subsubdir/sib_0"],
            page_for_testing(
                "subdir/subsubdir/sib_0.page",
                siblings=['subdir/subsubdir/sib_1', 'subdir/subsubdir/sib_2'],
                lighter=None, heavier='subdir/subsubdir/sib_1', tags=['tag0']))
        self.assertEqual(
            library.pages["subdir/subsubdir/index"],
            page_for_testing(
                "subdir/subsubdir/index.page",
                path="", filename="",
                siblings=['subdir/subsubdir/sib_0',
                          'subdir/subsubdir/sib_1',
                          'subdir/subsubdir/sib_2'],
                lighter=None, heavier=None, weight=None))
        self.assertEqual(
            sorted(X._replace(latest_timestamp=0) for X in library.tasks),
            sorted([
                Task(page_id='test',
                     latest_timestamp=0,
                     template='test',
                     output_path=Path('test.html')),
                Task(page_id='subdir/subsubdir/sib_0',
                     latest_timestamp=0,
                     template='sib',
                     output_path=Path('subdir/subsubdir/sib_0.html')),
                Task(page_id='subdir/subsubdir/sib_1',
                     latest_timestamp=0,
                     template='sib',
                     output_path=Path('subdir/subsubdir/sib_1.html')),
                Task(page_id='subdir/subsubdir/sib_2',
                     latest_timestamp=0,
                     template='sib',
                     output_path=Path('subdir/subsubdir/sib_2.html'))]))

    def test_suffix_processing(self):
        os.makedirs("/content/subdir")
        with self.subTest("xml suffix"):
            with open("/content/subdir/test.page", "w") as f:
                f.write(
                    "template = 'test'\n"
                    "suffix = '.xml'\n")
            library = build_library(Path("/content"))
            self.assertEqual(
                library.pages["subdir/test"],
                page_for_testing(
                    "subdir/test.page",
                    id='subdir/test',
                    filename='test.xml',
                    path='subdir/test.xml'))
        with self.subTest("empty suffix"):
            with open("/content/subdir/test.page", "w") as f:
                f.write(
                    "template = 'test'\n"
                    "suffix = ''\n")
            library = build_library(Path("/content"))
            self.assertEqual(
                library.pages["subdir/test"],
                page_for_testing(
                    "subdir/test.page",
                    id='subdir/test',
                    filename='test',
                    path='subdir/test'))
        with self.subTest("suffix not a string"):
            with open("/content/subdir/test.page", "w") as f:
                f.write(
                    "template = 'test'\n"
                    "suffix = 0\n")
            with self.assertRaises(TypeError) as cm:
                library = build_library(Path("/content"))
            self.assertNotEqual(str(cm.exception).find("must be a string"), -1)

    def test_malformed_page_file(self):
        os.makedirs("/content")
        # tags not a list
        with open("/content/test.page", "w") as f:
            f.write("tags = 'tag'")
        with self.assertRaises(TypeError) as cm:
            build_library(Path("/content"))
        self.assertNotEqual(str(cm.exception).find("list of strings"), -1)
        # weight not an integer or "None"
        with open("/content/test.page", "w") as f:
            f.write("weight = 'str'")
        with self.assertRaises(TypeError) as cm:
            build_library(Path("/content"))
        self.assertNotEqual(str(cm.exception).find("an integer"), -1)
        # invalid TOML for template -- missing quote marks
        with open("/content/test.page", "w") as f:
            f.write("template = not_a_str")
        with self.assertRaises(tomllib.TOMLDecodeError) as cm:
            build_library(Path("/content"))
        self.assertNotEqual(str(cm.exception).find("Invalid value"), -1)
        # template not a string
        with open("/content/test.page", "w") as f:
            f.write("template = 1")
        with self.assertRaises(TypeError) as cm:
            build_library(Path("/content"))
        self.assertNotEqual(str(cm.exception).find("must be a string"), -1)
        # content not a table
        with open("/content/test.page", "w") as f:
            f.write("content = '1'")
        with self.assertRaises(TypeError) as cm:
            build_library(Path("/content"))
        self.assertNotEqual(str(cm.exception).find("TOML table"), -1)
        with open("/content/test.page", "w") as f:
            f.write("content = [1, 2]")
        with self.assertRaises(TypeError) as cm:
            build_library(Path("/content"))
        self.assertNotEqual(str(cm.exception).find("TOML table"), -1)
        # file in content doesn't exist
        with open("/content/test.page", "w") as f:
            f.write("[content]\nmain = 'not_a_file'")
        with self.assertRaises(TypeError) as cm:
            build_library(Path("/content"))
        self.assertNotEqual(str(cm.exception).find("TOML table"), -1)


class TestCustomFilters(FFTestCase):

    def setUp(self):
        self.setUpPyfakefs()
        os.makedirs("/site/content")
        os.makedirs("/site/templates")
        os.makedirs("/site/public")

    class MockEnvironment():
        pass

    def test_latest_filter(self):
        env = TestCustomFilters.MockEnvironment()
        env.filters = {}
        library = Library({}, {}, {}, {}, {})
        define_jinja_filters(library, env)
        latest = env.filters["latest"]
        # a relative URL
        context = {"page": page_for_testing("test/dir/page.page")}
        library.versioned.update({
            Path("test/dir/my/style.css"): 1,
        })
        self.assertEqual(latest(context, "my/style.css"),
                         "my/style.1.css")
        # with .. and .
        self.assertEqual(latest(context, "my/other/.././style.css"),
                         "my/other/../style.1.css")
        # no versioned file
        self.assertEqual(latest(context, "my/script.css"), "my/script.css")
        # absolute
        self.assertEqual(latest(context, "/my/style.css"), "/my/style.css")
        self.assertEqual(latest(context, "/test/dir/my/style.css"),
                         "/test/dir/my/style.1.css")

    def test_markdown_filter(self):
        with open("/site/content/test.page", "w") as f:
            f.write("template = 'test.jinja'\ncontent.main = 'test.md'\n")
        with open("/site/templates/test.jinja", "w") as f:
            f.write("{{page.content.main | markdown}}")
        with open("/site/content/test.md", "w") as f:
            f.write("# Heading\n\nParagraph")
        library = build_library(Path("/site/content"))
        output_site(Path("/site/templates"), library, Path("/site/public"))
        self.assertEqual(Path("/site/public/test.html").read_text(),
                         "<h1>Heading</h1>\n<p>Paragraph</p>\n")

    def test_versioning_filter(self):
        os.makedirs("/content/css")
        for n in range(3, 6):
            with open(f"/content/css/test.{n}.css", "w") as f:
                f.write("")
        library = build_library(Path("/content"))
        self.assertEqual(library.versioned, {Path('css/test.css'): 5})


class TestQuickBuild(FFTestCase):

    def setUp(self):
        self.setUpPyfakefs()
        os.makedirs("/site/content/data")
        os.makedirs("/site/templates")

    def test_quick_build(self):

        def quick_build():
            build(
                Path("/site/content"),
                Path("/site/templates"),
                Path("/site/public"),
                True)
        # set up a test filesytem
        with open("/site/content/static", "w") as f:
            f.write("test")
        with open("/site/content/test.page", "w") as f:
            f.write('template = "test.jinja"\n'
                    'content.main = "data/content.html"')
        with open("/site/templates/test.jinja", "w") as f:
            f.write("{{page.content.main}}")
        with open("/site/templates/test-1.jinja", "w") as f:
            f.write("1 {{page.content.main}}")
        with open("/site/content/data/content.html", "w") as f:
            f.write("Test content")
        # no public directory yet, so should just build normally
        quick_build()
        with open("/site/public/test.html") as f:
            self.assertEqual(f.read(), "Test content")
        # change the content
        with open("/site/content/data/content.html", "w") as f:
            f.write("Test content!")
        quick_build()
        with open("/site/public/test.html") as f:
            self.assertEqual(f.read(), "Test content!")
        # check no changes means no update
        ts = os.stat("/site/public/test.html").st_mtime
        quick_build()
        self.assertEqual(os.stat("/site/public/test.html").st_mtime, ts)
        # check static file update
        with open("/site/content/static", "w") as f:
            f.write("changed")
        quick_build()
        with open("/site/public/static") as f:
            self.assertEqual(f.read(), "changed")
        # change the page file to use the other template, should update
        with open("/site/content/test.page", "w") as f:
            f.write('template = "test-1.jinja"\n'
                    'content.main = "data/content.html"')
        quick_build()
        with open("/site/public/test.html") as f:
            self.assertEqual(f.read(), "1 Test content!")
        # change the new template itself, doesn't update
        with open("/site/templates/test-1.jinja", "w") as f:
            f.write("2 {{page.content.main}}")
        quick_build()
        with open("/site/public/test.html") as f:
            self.assertEqual(f.read(), "1 Test content!")
