# Privacy

H2S Open Source Radar is designed to make context-aware recommendations without
recording the contents of your work.

## What is used by default

- Names of relevant applications currently running on the Mac.
- Recent project **file names and extensions** from configured local project roots.
- User-entered interests and local recommendation preferences.
- Public GitHub repository metadata returned by the GitHub Search API.
- Local application, selected audio plug-in, common CLI executable, and H2S-managed install names/paths used to determine whether a recommendation is already installed.
- Local hardware summary (architecture, macOS version, memory size, and free disk space) used to estimate compatibility.

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

## Easy Install data flow

When you select a project, Radar may query that project's public GitHub Releases API to locate a compatible macOS asset. Downloaded installer files are fetched directly from approved GitHub release hosts. H2S-managed install paths, versions, and installed sizes are stored only in the local Radar database.

No local application binaries, plug-ins, project files, or document contents are uploaded for compatibility checks.
