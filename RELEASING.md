# Releasing Sim-CPDLC

The tag is the version. Every file that carries a version number must say the
same thing before the tag is pushed, and the release workflow refuses to build
when it does not.

1. Pick the version `X.Y.Z` (the last release is the highest `v*` tag).
2. Run `python update_version.py X.Y.Z`. It rewrites `APP_VERSION` in
   `src/config.py`, the four version fields in `version_info.txt` and
   `MyAppVersion` in `sim-cpdlc.iss`.
3. Run `pytest`. `tests/test_release.py` fails if the three files disagree.
4. Commit: `git commit -am "Release X.Y.Z"` and push `main`.
5. Tag and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.

Pushing the tag starts `.github/workflows/build-and-release.yml`: it runs the
test suite, checks that `APP_VERSION` equals the tag, installs
`requirements-build.txt`, builds the executable with PyInstaller (the build
stops if `SimConnect.dll` is missing), builds the installer with Inno Setup and
attaches `Sim-CPDLC-X.Y.Z.exe` to a GitHub release for the tag.

If the version check fails, fix the files, commit, move the tag
(`git tag -f vX.Y.Z && git push -f origin vX.Y.Z`) and the workflow runs again.

A checkout that is not a packaged build shows `X.Y.Z (source)` in
`File > About` and never checks for updates automatically.
