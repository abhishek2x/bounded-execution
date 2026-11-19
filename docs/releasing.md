# Publishing to PyPI

Pushing the repository to GitHub does **not** publish a package. A PyPI
release requires a versioned source distribution and wheel to be built,
checked, and uploaded.

## Before the first release

1. Commit and push the source code to GitHub.
2. Run the full test suite on a Python 3.9+ environment that permits
   process pools; test supported Python versions before claiming them.
3. Run and retain benchmark results with their environment and workload
   metadata.
4. Review the README, changelog, license, package name availability, and
   distribution contents. This project's `MANIFEST.in` includes the
   documentation in the source distribution.
5. The current development version is `0.1.0.dev0`; use it for the
   TestPyPI trial. Choose the final release version, such as `0.1.0`,
   only after the trial passes.

## Build and verify locally

```sh
python -m pip install -e ".[release]"
python -m build --sdist --wheel
python -m twine check dist/*
```

Upload to TestPyPI first and install the exact uploaded version in a
clean environment to verify the wheel:

```sh
python -m twine upload --repository testpypi dist/*
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --no-deps \
  bounded-execution==0.1.0.dev0
```

Use a TestPyPI API token; at Twine's prompts, enter `__token__` as the
username and the token as the password. Never commit or expose the token.
TestPyPI and PyPI are separate indexes; a TestPyPI upload is not a
production release.

After the TestPyPI install and smoke tests pass, choose the final release
version and license, update `version` in `pyproject.toml` and the
changelog, then build and check fresh artifacts. Upload those final
artifacts to PyPI:

```sh
python -m twine upload dist/*
```

Use a PyPI API token or configure Trusted Publishing. Uploaded release
files cannot be replaced with different files under the same version,
so verify the version and artifacts before uploading. Tag the release
(for example, `v0.1.0`) and create a GitHub release pointing to the
changelog after the upload succeeds.
