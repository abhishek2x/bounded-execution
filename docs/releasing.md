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
5. Follow the version sequence below; each upload needs a new version.

| Version      | Purpose                | Index    |
| ------------ | ---------------------- | -------- |
| `0.1.0.dev0` | Development snapshot   | TestPyPI |
| `0.1.0a1`    | First public alpha     | PyPI     |
| `0.1.0a2`    | Subsequent alpha fixes | PyPI     |
| `0.1.0`      | First stable release   | PyPI     |

## Build and verify locally

```sh
python -m pip install -e ".[release]"
```

For the TestPyPI trial, set `version` in `pyproject.toml` to
`0.1.0.dev0`, then build fresh artifacts, check them, and upload only
those files:

```sh
test_dir="$(mktemp -d "$TMPDIR/bounded-execution-testpypi.XXXXXX")"
python -m build --sdist --wheel --outdir "$test_dir"
python -m twine check "$test_dir"/*
python -m twine upload --repository testpypi "$test_dir"/*
```

Install the exact TestPyPI version in a clean environment to verify the
uploaded wheel:

```sh
test_env="$(mktemp -d "$TMPDIR/bounded-execution-test-install.XXXXXX")"
python -m venv "$test_env"
"$test_env/bin/python" -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --no-deps \
  bounded-execution==0.1.0.dev0
```

Use a TestPyPI API token; at Twine's prompts, enter `__token__` as the
username and the token as the password. Never commit or expose the token.
TestPyPI and PyPI are separate indexes; a TestPyPI upload is not a
production release.

## Publish the first alpha to PyPI

After the TestPyPI install and smoke tests pass, set `version` in
`pyproject.toml` to `0.1.0a1`, update the changelog, and build and check
fresh artifacts:

```sh
release_dir="$(mktemp -d "$TMPDIR/bounded-execution-pypi.XXXXXX")"
python -m build --sdist --wheel --outdir "$release_dir"
python -m twine check "$release_dir"/*
```

Upload those artifacts to production PyPI:

```sh
python -m twine upload --repository pypi "$release_dir"/*
```

Use a PyPI API token or configure Trusted Publishing. Uploaded release
files cannot be replaced. To publish an update, change the version first
(for example, from `0.1.0a1` to `0.1.0a2`), update the changelog, then
build, check, and upload the new artifacts with the same commands.

After the alpha period, use `0.1.0` for the first stable release. Tag
each release and create a GitHub release pointing to the changelog after
its upload succeeds.
