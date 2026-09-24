# Putting the dashboard online with GitHub (free)

About 15 minutes, all in the browser. No software to install.

Your live dashboard will be at:

    https://YOUR-USERNAME.github.io/dtm-nigeria-tracker/

## Why GitHub Pages

| Free option | Runs the hourly harvest? | Always on? | Verdict |
|---|---|---|---|
| **GitHub Pages + GitHub Actions** | Yes, built in, unlimited for public repos | Yes, never sleeps | **Best fit.** Hosting, scheduling and data history in one free account |
| Netlify / Cloudflare Pages | No, needs GitHub Actions anyway | Yes | Fine as an alternative front end, adds a second account |
| Render (free tier) | Only by keeping a server awake | Sleeps after 15 min idle | Slow first load, monthly hour limits |
| Hugging Face Spaces | Possible, more complex | Sleeps when idle | Good only if you later want the Claude assistant online |

## 1. Create your GitHub account

Go to https://github.com/signup. Use your work email if possible, and choose your own username and a strong password. Keep them to yourself; nobody, including an AI assistant, needs your password. Turn on two-factor authentication when GitHub offers it.

## 2. Create the repository

1. Click **+** (top right), then **New repository**.
2. Repository name: `dtm-nigeria-tracker`
3. Choose **Public**. GitHub Pages and unlimited Actions minutes are free only for public repositories. The data is public DTM reports, so nothing confidential is exposed. Never put passwords or API keys in it.
4. Tick **Add a README file**, then **Create repository**.

## 3. Upload the files

1. Unzip `dtm-nigeria-monitor.zip` on your computer.
2. In the repository, click **Add file**, then **Upload files**.
3. Open the unzipped `dtm-nigeria-monitor` folder, select **everything inside it** (including the `.github` folder), and drag it onto the upload page.
4. Click **Commit changes**.

Check that the upload included the workflow: you should see a `.github` folder in the repository. If you don't (Macs hide folders starting with a dot), click **Add file**, then **Create new file**, type the name `.github/workflows/harvest.yml`, paste in the contents of that file from the zip, and commit.

## 4. Allow the workflow to save new data

**Settings**, then **Actions**, then **General**. Under "Workflow permissions" choose **Read and write permissions**, then **Save**.

## 5. Turn on the website

**Settings**, then **Pages**. Under "Build and deployment", set **Source** to **GitHub Actions**.

## 6. Run the first harvest

1. Open the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Click **Harvest DTM Nigeria reports** on the left, then **Run workflow**, keep mode **full**, and click the green **Run workflow** button.
3. The first run reads every Nigeria report page, so it can take 30 to 90 minutes. A green tick means it worked.

Open `https://YOUR-USERNAME.github.io/dtm-nigeria-tracker/`. Bookmark it and share it with colleagues; they don't need a GitHub account to view it.

## How it stays up to date

Every hour the workflow checks the newest pages of dtm.iom.int/nigeria and adds any new report within about a minute. Every night it does a full crawl to catch anything missed. Open dashboards check for new data every 5 minutes and when you return to the tab, then update themselves without losing your filters, show a notice listing the new reports, and mark them "New" in the table.

So a report published on dtm.iom.int normally appears on the dashboard within about an hour.

## Updating files later

To change a keyword or replace a file: open it in the repository, click the pencil icon (or **Add file**, then **Upload files** to replace it with a new version from your computer), then **Commit changes**. The next workflow run uses the new version. To publish the change straight away, run the workflow by hand from the Actions tab.

## If something goes wrong

GitHub emails you if a run fails. Open the failed run in the Actions tab and read the last lines of the "Harvest dtm.iom.int" step.

"No report pages could be reached on dtm.iom.int" means the website refused GitHub's servers. Your existing data is kept. Try again later; if it keeps happening, run `python scrape.py` on your own computer and upload the new `data` files to the repository instead, and the website will update from those.

Many reports in "Other / Unclassified" means some titles use wording the keyword rules don't cover. Edit `config/taxonomy.json` in the repository (click the file, then the pencil icon) and run the workflow again.

GitHub pauses scheduled workflows in repositories with no activity for 60 days. New reports create activity, so this is unlikely, but if the Actions tab shows a paused notice, click to re-enable it.

## The AI assistant on the website

The GitHub website has no server, so its assistant is the built-in offline one: it answers counts and applies filters from typed questions, with no key needed. The Claude-powered assistant runs in the claude.ai version of the dashboard (load the `data/reports.json` file from your repository into it), or on your own computer with `server.py` and an Anthropic API key.
