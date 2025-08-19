#!/bin/bash

cd "$(dirname "$(readlink -f "$0")")"
mkdir -p website/site
mkdir -p build

. venv/bin/activate

./make-shiv

cd docs
../ssg.py
cd ..

cp -av docs/public/* website/
cp ssg.py website/downloads/
cp -av old/* website/downloads/
rm -r docs/public

cp -av ssg.py starter-site/templates starter-site/content website/site/
echo "ssg.py" > website/site/ssg.bat
cd website
zip -r starter.zip site
mv starter.zip downloads/
rm -r site
zip -r ../build/website.zip *
cd ..

rm ssg.py
rm -r website

deactivate
