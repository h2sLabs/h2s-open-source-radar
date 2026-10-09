# Privacy

H2S Open Source Radar is designed to make context-aware recommendations without
recording the contents of your work.

## What is used by default

- Names of relevant applications currently running on the Mac.
- Recent project **file names and extensions** from configured local project roots.
- User-entered interests and local recommendation preferences.
- Public GitHub repository metadata returned by the GitHub Search API.

## What is not collected by default

- Keystrokes.
- Screenshots or screen recordings.
- Clipboard contents.
- File bodies or document contents.
- Audio or microphone recordings.

Context and recommendation data are stored locally in
`~/Library/Application Support/H2S Open Source Radar/`.

The app sends search queries to GitHub when refreshing recommendations. If a
`GITHUB_TOKEN` environment variable is supplied, it is used only for GitHub API
authentication and is not written to the app database by this project.
