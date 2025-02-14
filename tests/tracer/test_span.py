# -*- coding: utf-8 -*-
import sys
import time
from unittest.case import SkipTest

import mock
import pytest

from ddtrace.constants import ANALYTICS_SAMPLE_RATE_KEY
from ddtrace.constants import ENV_KEY
from ddtrace.constants import SERVICE_VERSION_KEY
from ddtrace.constants import SPAN_MEASURED_KEY
from ddtrace.constants import VERSION_KEY
from ddtrace.ext import SpanTypes
from ddtrace.ext import errors
from ddtrace.span import Span
from tests.utils import TracerTestCase
from tests.utils import assert_is_measured
from tests.utils import assert_is_not_measured


class SpanTestCase(TracerTestCase):
    def test_ids(self):
        s = Span(tracer=None, name="span.test")
        assert s.trace_id
        assert s.span_id
        assert not s.parent_id

        s2 = Span(tracer=None, name="t", trace_id=1, span_id=2, parent_id=1)
        assert s2.trace_id == 1
        assert s2.span_id == 2
        assert s2.parent_id == 1

    def test_tags(self):
        s = Span(tracer=None, name="test.span")
        s.set_tag("a", "a")
        s.set_tag("b", 1)
        s.set_tag("c", "1")
        d = s.to_dict()
        assert d["meta"] == dict(a="a", c="1")
        assert d["metrics"] == dict(b=1)

    def test_numeric_tags(self):
        s = Span(tracer=None, name="test.span")
        s.set_tag("negative", -1)
        s.set_tag("zero", 0)
        s.set_tag("positive", 1)
        s.set_tag("large_int", 2 ** 53)
        s.set_tag("really_large_int", (2 ** 53) + 1)
        s.set_tag("large_negative_int", -(2 ** 53))
        s.set_tag("really_large_negative_int", -((2 ** 53) + 1))
        s.set_tag("float", 12.3456789)
        s.set_tag("negative_float", -12.3456789)
        s.set_tag("large_float", 2.0 ** 53)
        s.set_tag("really_large_float", (2.0 ** 53) + 1)

        d = s.to_dict()
        assert d["meta"] == dict(
            really_large_int=str(((2 ** 53) + 1)),
            really_large_negative_int=str(-((2 ** 53) + 1)),
        )
        assert d["metrics"] == {
            "negative": -1,
            "zero": 0,
            "positive": 1,
            "large_int": 2 ** 53,
            "large_negative_int": -(2 ** 53),
            "float": 12.3456789,
            "negative_float": -12.3456789,
            "large_float": 2.0 ** 53,
            "really_large_float": (2.0 ** 53) + 1,
        }

    def test_set_tag_bool(self):
        s = Span(tracer=None, name="test.span")
        s.set_tag("true", True)
        s.set_tag("false", False)

        d = s.to_dict()
        assert d["meta"] == dict(true="True", false="False")
        assert "metrics" not in d

    def test_set_tag_metric(self):
        s = Span(tracer=None, name="test.span")

        s.set_tag("test", "value")
        assert s.meta == dict(test="value")
        assert s.metrics == dict()

        s.set_tag("test", 1)
        assert s.meta == dict()
        assert s.metrics == dict(test=1)

    def test_set_valid_metrics(self):
        s = Span(tracer=None, name="test.span")
        s.set_metric("a", 0)
        s.set_metric("b", -12)
        s.set_metric("c", 12.134)
        s.set_metric("d", 1231543543265475686787869123)
        s.set_metric("e", "12.34")
        d = s.to_dict()
        expected = {
            "a": 0,
            "b": -12,
            "c": 12.134,
            "d": 1231543543265475686787869123,
            "e": 12.34,
        }
        assert d["metrics"] == expected

    def test_set_invalid_metric(self):
        s = Span(tracer=None, name="test.span")

        invalid_metrics = [None, {}, [], s, "quarante-douze", float("nan"), float("inf"), 1j]

        for i, m in enumerate(invalid_metrics):
            k = str(i)
            s.set_metric(k, m)
            assert s.get_metric(k) is None

    def test_set_numpy_metric(self):
        try:
            import numpy as np
        except ImportError:
            raise SkipTest("numpy not installed")
        s = Span(tracer=None, name="test.span")
        s.set_metric("a", np.int64(1))
        assert s.get_metric("a") == 1
        assert type(s.get_metric("a")) == float

    def test_tags_not_string(self):
        # ensure we can cast as strings
        class Foo(object):
            def __repr__(self):
                1 / 0

        s = Span(tracer=None, name="test.span")
        s.set_tag("a", Foo())

    def test_finish(self):
        # ensure span.finish() marks the end time of the span
        s = Span(None, "test.span")
        sleep = 0.05
        time.sleep(sleep)
        s.finish()
        assert s.duration >= sleep, "%s < %s" % (s.duration, sleep)

    def test_finish_no_tracer(self):
        # ensure finish works with no tracer without raising exceptions
        s = Span(tracer=None, name="test.span")
        s.finish()

    def test_finish_called_multiple_times(self):
        # we should only record a span the first time finish is called on it
        s = Span(self.tracer, "bar")
        s.finish()
        s.finish()

    def test_finish_set_span_duration(self):
        # If set the duration on a span, the span should be recorded with this
        # duration
        s = Span(tracer=None, name="test.span")
        s.duration = 1337.0
        s.finish()
        assert s.duration == 1337.0

    def test_setter_casts_duration_ns_as_int(self):
        s = Span(tracer=None, name="test.span")
        s.duration = 3.2
        s.finish()
        assert s.duration == 3.2
        assert s.duration_ns == 3200000000
        assert isinstance(s.duration_ns, int)

    def test_get_span_returns_none_by_default(self):
        s = Span(tracer=None, name="test.span")
        assert s.duration is None

    def test_traceback_with_error(self):
        s = Span(None, "test.span")
        try:
            1 / 0
        except ZeroDivisionError:
            s.set_traceback()
        else:
            assert 0, "should have failed"

        assert s.error
        assert "by zero" in s.get_tag(errors.ERROR_MSG)
        assert "ZeroDivisionError" in s.get_tag(errors.ERROR_TYPE)

    def test_traceback_without_error(self):
        s = Span(None, "test.span")
        s.set_traceback()
        assert not s.error
        assert not s.get_tag(errors.ERROR_MSG)
        assert not s.get_tag(errors.ERROR_TYPE)
        assert "in test_traceback_without_error" in s.get_tag(errors.ERROR_STACK)

    def test_ctx_mgr(self):
        s = Span(self.tracer, "bar")
        assert not s.duration
        assert not s.error

        e = Exception("boo")
        try:
            with s:
                time.sleep(0.01)
                raise e
        except Exception as out:
            assert out == e
            assert s.duration > 0, s.duration
            assert s.error
            assert s.get_tag(errors.ERROR_MSG) == "boo"
            assert "Exception" in s.get_tag(errors.ERROR_TYPE)
            assert s.get_tag(errors.ERROR_STACK)

        else:
            assert 0, "should have failed"

    def test_span_type(self):
        s = Span(tracer=None, name="test.span", service="s", resource="r", span_type=SpanTypes.WEB)
        s.set_tag("a", "1")
        s.set_meta("b", "2")
        s.finish()

        d = s.to_dict()
        assert d
        assert d["span_id"] == s.span_id
        assert d["trace_id"] == s.trace_id
        assert d["parent_id"] == s.parent_id
        assert d["meta"] == {"a": "1", "b": "2"}
        assert d["type"] == "web"
        assert d["error"] == 0
        assert type(d["error"]) == int

    def test_span_to_dict(self):
        s = Span(tracer=None, name="test.span", service="s", resource="r")
        s.span_type = "foo"
        s.set_tag("a", "1")
        s.set_meta("b", "2")
        s.finish()

        d = s.to_dict()
        assert d
        assert d["span_id"] == s.span_id
        assert d["trace_id"] == s.trace_id
        assert d["parent_id"] == s.parent_id
        assert d["meta"] == {"a": "1", "b": "2"}
        assert d["type"] == "foo"
        assert d["error"] == 0
        assert type(d["error"]) == int

    def test_span_to_dict_sub(self):
        parent = Span(tracer=None, name="test.span", service="s", resource="r")
        s = Span(tracer=None, name="test.span", service="s", resource="r")
        s._parent = parent
        s.span_type = "foo"
        s.set_tag("a", "1")
        s.set_meta("b", "2")
        s.finish()

        d = s.to_dict()
        assert d
        assert d["span_id"] == s.span_id
        assert d["trace_id"] == s.trace_id
        assert d["parent_id"] == s.parent_id
        assert d["meta"] == {"a": "1", "b": "2"}
        assert d["type"] == "foo"
        assert d["error"] == 0
        assert type(d["error"]) == int

    def test_span_boolean_err(self):
        s = Span(tracer=None, name="foo.bar", service="s", resource="r")
        s.error = True
        s.finish()

        d = s.to_dict()
        assert d
        assert d["error"] == 1
        assert type(d["error"]) == int

    @mock.patch("ddtrace.span.log")
    def test_numeric_tags_none(self, span_log):
        s = Span(tracer=None, name="test.span")
        s.set_tag(ANALYTICS_SAMPLE_RATE_KEY, None)
        d = s.to_dict()
        assert d
        assert "metrics" not in d

        # Ensure we log a debug message
        span_log.debug.assert_called_once_with(
            "ignoring not number metric %s:%s",
            ANALYTICS_SAMPLE_RATE_KEY,
            None,
        )

    def test_numeric_tags_true(self):
        s = Span(tracer=None, name="test.span")
        s.set_tag(ANALYTICS_SAMPLE_RATE_KEY, True)
        d = s.to_dict()
        assert d
        expected = {ANALYTICS_SAMPLE_RATE_KEY: 1.0}
        assert d["metrics"] == expected

    def test_numeric_tags_value(self):
        s = Span(tracer=None, name="test.span")
        s.set_tag(ANALYTICS_SAMPLE_RATE_KEY, 0.5)
        d = s.to_dict()
        assert d
        expected = {ANALYTICS_SAMPLE_RATE_KEY: 0.5}
        assert d["metrics"] == expected

    def test_numeric_tags_bad_value(self):
        s = Span(tracer=None, name="test.span")
        s.set_tag(ANALYTICS_SAMPLE_RATE_KEY, "Hello")
        d = s.to_dict()
        assert d
        assert "metrics" not in d

    def test_set_tag_none(self):
        s = Span(tracer=None, name="root.span", service="s", resource="r")
        assert s.meta == dict()

        s.set_tag("custom.key", "100")

        assert s.meta == {"custom.key": "100"}

        s.set_tag("custom.key", None)

        assert s.meta == {"custom.key": "None"}

    def test_duration_zero(self):
        s = Span(tracer=None, name="foo.bar", service="s", resource="r", start=123)
        s.finish(finish_time=123)
        assert s.duration_ns == 0
        assert s.duration == 0

    def test_start_int(self):
        s = Span(tracer=None, name="foo.bar", service="s", resource="r", start=123)
        assert s.start == 123
        assert s.start_ns == 123000000000

        s = Span(tracer=None, name="foo.bar", service="s", resource="r", start=123.123)
        assert s.start == 123.123
        assert s.start_ns == 123123000000

        s = Span(tracer=None, name="foo.bar", service="s", resource="r", start=123.123)
        s.start = 234567890.0
        assert s.start == 234567890
        assert s.start_ns == 234567890000000000

    def test_duration_int(self):
        s = Span(tracer=None, name="foo.bar", service="s", resource="r")
        s.finish()
        assert isinstance(s.duration_ns, int)
        assert isinstance(s.duration, float)

        s = Span(tracer=None, name="foo.bar", service="s", resource="r", start=123)
        s.finish(finish_time=123.2)
        assert s.duration_ns == 200000000
        assert s.duration == 0.2

        s = Span(tracer=None, name="foo.bar", service="s", resource="r", start=123.1)
        s.finish(finish_time=123.2)
        assert s.duration_ns == 100000000
        assert s.duration == 0.1

        s = Span(tracer=None, name="foo.bar", service="s", resource="r", start=122)
        s.finish(finish_time=123)
        assert s.duration_ns == 1000000000
        assert s.duration == 1

    def test_set_tag_version(self):
        s = Span(tracer=None, name="test.span")
        s.set_tag(VERSION_KEY, "1.2.3")
        assert s.get_tag(VERSION_KEY) == "1.2.3"
        assert s.get_tag(SERVICE_VERSION_KEY) is None

        s.set_tag(SERVICE_VERSION_KEY, "service.version")
        assert s.get_tag(VERSION_KEY) == "service.version"
        assert s.get_tag(SERVICE_VERSION_KEY) == "service.version"

    def test_set_tag_env(self):
        s = Span(tracer=None, name="test.span")
        s.set_tag(ENV_KEY, "prod")
        assert s.get_tag(ENV_KEY) == "prod"


@pytest.mark.parametrize(
    "value,assertion",
    [
        (None, assert_is_measured),
        (1, assert_is_measured),
        (1.0, assert_is_measured),
        (-1, assert_is_measured),
        (True, assert_is_measured),
        ("true", assert_is_measured),
        # DEV: Ends up being measured because we do `bool("false")` which is `True`
        ("false", assert_is_measured),
        (0, assert_is_not_measured),
        (0.0, assert_is_not_measured),
        (False, assert_is_not_measured),
    ],
)
def test_set_tag_measured(value, assertion):
    s = Span(tracer=None, name="test.span")
    s.set_tag(SPAN_MEASURED_KEY, value)
    assertion(s)


def test_set_tag_measured_not_set():
    # Span is not measured by default
    s = Span(tracer=None, name="test.span")
    assert_is_not_measured(s)


def test_set_tag_measured_no_value():
    s = Span(tracer=None, name="test.span")
    s.set_tag(SPAN_MEASURED_KEY)
    assert_is_measured(s)


def test_set_tag_measured_change_value():
    s = Span(tracer=None, name="test.span")
    s.set_tag(SPAN_MEASURED_KEY, True)
    assert_is_measured(s)

    s.set_tag(SPAN_MEASURED_KEY, False)
    assert_is_not_measured(s)

    s.set_tag(SPAN_MEASURED_KEY)
    assert_is_measured(s)


@mock.patch("ddtrace.span.log")
def test_span_key(span_log):
    # Span tag keys must be strings
    s = Span(tracer=None, name="test.span")

    s.set_tag(123, True)
    span_log.warning.assert_called_once_with("Ignoring tag pair %s:%s. Key must be a string.", 123, True)
    assert s.get_tag(123) is None
    assert s.get_tag("123") is None

    span_log.reset_mock()

    s.set_tag(None, "val")
    span_log.warning.assert_called_once_with("Ignoring tag pair %s:%s. Key must be a string.", None, "val")
    assert s.get_tag(123.32) is None


def test_span_finished():
    span = Span(None, None)
    assert span.finished is False
    assert span.duration_ns is None

    span.finished = True
    assert span.finished is True
    assert span.duration_ns is not None
    duration = span.duration_ns

    span.finished = True
    assert span.finished is True
    assert span.duration_ns == duration

    span.finished = False
    assert span.finished is False

    span.finished = True
    assert span.finished is True
    assert span.duration_ns != duration


def test_span_unicode_set_tag():
    span = Span(None, None)
    span.set_tag("key", u"😌")
    span.set_tag("😐", u"😌")
    span._set_str_tag("key", u"😌")
    span._set_str_tag(u"😐", u"😌")


@pytest.mark.skipif(sys.version_info.major != 2, reason="This test only applies Python 2")
@mock.patch("ddtrace.span.log")
def test_span_binary_unicode_set_tag(span_log):
    span = Span(None, None)
    span.set_tag("key", "🤔")
    span._set_str_tag("key_str", "🤔")
    # only span.set_tag() will fail
    span_log.warning.assert_called_once_with("error setting tag %s, ignoring it", "key", exc_info=True)
    assert "key" not in span.meta
    assert span.meta["key_str"] == u"🤔"


@pytest.mark.skipif(sys.version_info.major == 2, reason="This test does not apply to Python 2")
@mock.patch("ddtrace.span.log")
def test_span_bytes_string_set_tag(span_log):
    span = Span(None, None)
    span.set_tag("key", b"\xf0\x9f\xa4\x94")
    span._set_str_tag("key_str", b"\xf0\x9f\xa4\x94")
    assert span.meta["key"] == "b'\\xf0\\x9f\\xa4\\x94'"
    assert span.meta["key_str"] == "🤔"
    span_log.warning.assert_not_called()


@mock.patch("ddtrace.span.log")
def test_span_encoding_set_str_tag(span_log):
    span = Span(None, None)
    span._set_str_tag("foo", u"/?foo=bar&baz=정상처리".encode("euc-kr"))
    span_log.warning.assert_not_called()
    assert span.meta["foo"] == u"/?foo=bar&baz=����ó��"


@mock.patch("ddtrace.span.log")
def test_span_nonstring_set_str_tag(span_log):
    span = Span(None, None)
    with pytest.raises(TypeError):
        span._set_str_tag("foo", dict(a=1))
    assert "foo" not in span.meta


def test_span_ignored_exceptions():
    s = Span(None, None)
    s._ignore_exception(ValueError)

    with pytest.raises(ValueError):
        with s:
            raise ValueError()

    assert s.error == 0
    assert s.get_tag(errors.ERROR_MSG) is None
    assert s.get_tag(errors.ERROR_TYPE) is None
    assert s.get_tag(errors.ERROR_STACK) is None

    s = Span(None, None)
    s._ignore_exception(ValueError)

    with pytest.raises(ValueError):
        with s:
            raise ValueError()

    with pytest.raises(RuntimeError):
        with s:
            raise RuntimeError()

    assert s.error == 1
    assert s.get_tag(errors.ERROR_MSG) is not None
    assert "RuntimeError" in s.get_tag(errors.ERROR_TYPE)
    assert s.get_tag(errors.ERROR_STACK) is not None


def test_span_ignored_exception_multi():
    s = Span(None, None)
    s._ignore_exception(ValueError)
    s._ignore_exception(RuntimeError)

    with pytest.raises(ValueError):
        with s:
            raise ValueError()

    with pytest.raises(RuntimeError):
        with s:
            raise RuntimeError()

    assert s.error == 0
    assert s.get_tag(errors.ERROR_MSG) is None
    assert s.get_tag(errors.ERROR_TYPE) is None
    assert s.get_tag(errors.ERROR_STACK) is None


def test_span_ignored_exception_subclass():
    s = Span(None, None)
    s._ignore_exception(Exception)

    with pytest.raises(ValueError):
        with s:
            raise ValueError()

    with pytest.raises(RuntimeError):
        with s:
            raise RuntimeError()

    assert s.error == 0
    assert s.get_tag(errors.ERROR_MSG) is None
    assert s.get_tag(errors.ERROR_TYPE) is None
    assert s.get_tag(errors.ERROR_STACK) is None


def test_on_finish_single_callback():
    m = mock.Mock()
    s = Span(None, "test", on_finish=[m])
    m.assert_not_called()
    s.finish()
    m.assert_called_once_with(s)


def test_on_finish_multi_callback():
    m1 = mock.Mock()
    m2 = mock.Mock()
    s = Span(None, "test", on_finish=[m1, m2])
    s.finish()
    m1.assert_called_once_with(s)
    m2.assert_called_once_with(s)


@pytest.mark.parametrize("arg", ["span_id", "trace_id", "parent_id"])
def test_span_preconditions(arg):
    Span(None, "test", **{arg: None})
    with pytest.raises(TypeError):
        Span(None, "test", **{arg: "foo"})
