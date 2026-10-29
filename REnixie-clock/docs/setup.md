# Setup

## 1. Create the repo

On github.com: **New repository**. GitHub does not allow `;` in repo names, so name it `REnixie-clock`
(the `;` lives in the README title and the repo description). Public, no template files.

## 2. Put these files in it

From a terminal in this folder (Git for Windows is fine):

```
git init -b main
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USER/REnixie-clock.git
git push -u origin main
```

Dragging the folder into GitHub's web uploader usually skips the hidden `.github` folder, which is
why the terminal route is recommended.

## 3. Let the Action write to the repo

Settings -> Actions -> General -> Workflow permissions -> **Read and write permissions** -> Save.

## 4. First run

Actions tab -> *update-worldline* -> **Run workflow**. When it finishes you should see a new branch
`worldline-data` containing `divergence.txt`. Open the run's log: it lists any feed that failed.

## 5. Replace YOUR_USER

Search the repo for `YOUR_USER` (README.md and `firmware/worldline_online/worldline_online.ino`).

## 6. Optional: better scoring

Settings -> Secrets and variables -> Actions: add secret `ANTHROPIC_API_KEY` and variable
`WORLDLINE_SCORER` = `blend`. The default `lexicon` needs nothing.

## Local commands

```
python worldline/worldline.py run --data /tmp/wd        # one live update, needs internet
python worldline/worldline.py score "Peace deal signed"  # score one headline
python -m unittest discover -s worldline/tests          # run the tests
```
