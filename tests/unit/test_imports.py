import reolink_camera_control as pkg


def test_public_api_is_importable():
    for name in pkg.__all__:
        assert hasattr(pkg, name), name


def test_exception_hierarchy():
    for exc in (pkg.ReolinkAuthError, pkg.ReolinkCommandError,
                pkg.ReolinkConnectionError, pkg.ReolinkAudioError):
        assert issubclass(exc, pkg.ReolinkError)


def test_version_string():
    assert pkg.__version__.count(".") == 2
