import pytest
import requests
import responses

import gitlab
from gitlab import GitlabHttpError, GitlabList, GitlabParsingError, RedirectError
from tests.unit import helpers

MATCH_EMPTY_QUERY_PARAMS = [responses.matchers.query_param_matcher({})]


def test_build_url(gl):
    r = gl._build_url("http://localhost/api/v4")
    assert r == "http://localhost/api/v4"
    r = gl._build_url("https://localhost/api/v4")
    assert r == "https://localhost/api/v4"
    r = gl._build_url("/projects")
    assert r == "http://localhost/api/v4/projects"


@responses.activate
def test_http_request(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.GET,
        url=url,
        json=[{"name": "project1"}],
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    http_r = gl.http_request("get", "/projects")
    http_r.json()
    assert http_r.status_code == 200
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_http_request_404(gl):
    url = "http://localhost/api/v4/not_there"
    responses.add(
        method=responses.GET,
        url=url,
        json={},
        status=400,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabHttpError):
        gl.http_request("get", "/not_there")
    assert responses.assert_call_count(url, 1) is True


@responses.activate
@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_http_request_with_only_failures(gl, status_code):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.GET,
        url=url,
        json={},
        status=status_code,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabHttpError):
        gl.http_request("get", "/projects")

    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_http_request_with_retry_on_method_for_transient_failures(gl):
    call_count = 0
    calls_before_success = 3

    url = "http://localhost/api/v4/projects"

    def request_callback(request):
        nonlocal call_count
        call_count += 1
        status_code = 200 if call_count >= calls_before_success else 500
        headers = {}
        body = "[]"

        return (status_code, headers, body)

    responses.add_callback(
        method=responses.GET,
        url=url,
        callback=request_callback,
        content_type="application/json",
    )

    http_r = gl.http_request("get", "/projects", retry_transient_errors=True)

    assert http_r.status_code == 200
    assert len(responses.calls) == calls_before_success


@responses.activate
def test_http_request_with_retry_on_class_for_transient_failures(gl_retry):
    call_count = 0
    calls_before_success = 3

    url = "http://localhost/api/v4/projects"

    def request_callback(request: requests.models.PreparedRequest):
        nonlocal call_count
        call_count += 1
        status_code = 200 if call_count >= calls_before_success else 500
        headers = {}
        body = "[]"

        return (status_code, headers, body)

    responses.add_callback(
        method=responses.GET,
        url=url,
        callback=request_callback,
        content_type="application/json",
    )

    http_r = gl_retry.http_request("get", "/projects", retry_transient_errors=True)

    assert http_r.status_code == 200
    assert len(responses.calls) == calls_before_success


@responses.activate
def test_http_request_with_retry_on_class_and_method_for_transient_failures(gl_retry):
    call_count = 0
    calls_before_success = 3

    url = "http://localhost/api/v4/projects"

    def request_callback(request):
        nonlocal call_count
        call_count += 1
        status_code = 200 if call_count >= calls_before_success else 500
        headers = {}
        body = "[]"

        return (status_code, headers, body)

    responses.add_callback(
        method=responses.GET,
        url=url,
        callback=request_callback,
        content_type="application/json",
    )

    with pytest.raises(GitlabHttpError):
        gl_retry.http_request("get", "/projects", retry_transient_errors=False)

    assert len(responses.calls) == 1


def create_redirect_response(
    *, response: requests.models.Response, http_method: str, api_path: str
) -> requests.models.Response:
    """Create a Requests response object that has a redirect in it"""

    assert api_path.startswith("/")
    http_method = http_method.upper()

    # Create a history which contains our original request which is redirected
    history = [
        helpers.httmock_response(
            status_code=302,
            content="",
            headers={"Location": f"http://example.com/api/v4{api_path}"},
            reason="Moved Temporarily",
            request=response.request,
        )
    ]

    # Create a "prepped" Request object to be the final redirect. The redirect
    # will be a "GET" method as Requests changes the method to "GET" when there
    # is a 301/302 redirect code.
    req = requests.Request(
        method="GET",
        url=f"http://example.com/api/v4{api_path}",
    )
    prepped = req.prepare()

    resp_obj = helpers.httmock_response(
        status_code=200,
        content="",
        headers={},
        reason="OK",
        elapsed=5,
        request=prepped,
    )
    resp_obj.history = history
    return resp_obj


def test_http_request_302_get_does_not_raise(gl):
    """Test to show that a redirect of a GET will not cause an error"""

    method = "get"
    api_path = "/user/status"
    url = f"http://localhost/api/v4{api_path}"

    def response_callback(
        response: requests.models.Response,
    ) -> requests.models.Response:
        return create_redirect_response(
            response=response, http_method=method, api_path=api_path
        )

    with responses.RequestsMock(response_callback=response_callback) as req_mock:
        req_mock.add(
            method=responses.GET,
            url=url,
            status=302,
            match=MATCH_EMPTY_QUERY_PARAMS,
        )
        gl.http_request(verb=method, path=api_path)


def test_http_request_302_put_raises_redirect_error(gl):
    """Test to show that a redirect of a PUT will cause an error"""

    method = "put"
    api_path = "/user/status"
    url = f"http://localhost/api/v4{api_path}"

    def response_callback(
        response: requests.models.Response,
    ) -> requests.models.Response:
        return create_redirect_response(
            response=response, http_method=method, api_path=api_path
        )

    with responses.RequestsMock(response_callback=response_callback) as req_mock:
        req_mock.add(
            method=responses.PUT,
            url=url,
            status=302,
            match=MATCH_EMPTY_QUERY_PARAMS,
        )
        with pytest.raises(RedirectError) as exc:
            gl.http_request(verb=method, path=api_path)
    error_message = exc.value.error_message
    assert "Moved Temporarily" in error_message
    assert "http://localhost/api/v4/user/status" in error_message
    assert "http://example.com/api/v4/user/status" in error_message


@responses.activate
def test_get_request(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.GET,
        url=url,
        json={"name": "project1"},
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    result = gl.http_get("/projects")
    assert isinstance(result, dict)
    assert result["name"] == "project1"
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_get_request_raw(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.GET,
        url=url,
        content_type="application/octet-stream",
        body="content",
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    result = gl.http_get("/projects")
    assert result.content.decode("utf-8") == "content"
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_get_request_404(gl):
    url = "http://localhost/api/v4/not_there"
    responses.add(
        method=responses.GET,
        url=url,
        json=[],
        status=404,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabHttpError):
        gl.http_get("/not_there")
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_get_request_invalid_data(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.GET,
        url=url,
        body='["name": "project1"]',
        content_type="application/json",
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabParsingError):
        result = gl.http_get("/projects")
        print(type(result))
        print(result.content)
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_list_request(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.GET,
        url=url,
        json=[{"name": "project1"}],
        headers={"X-Total": "1"},
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    result = gl.http_list("/projects", as_list=True)
    assert isinstance(result, list)
    assert len(result) == 1

    result = gl.http_list("/projects", as_list=False)
    assert isinstance(result, GitlabList)
    assert len(result) == 1

    result = gl.http_list("/projects", all=True)
    assert isinstance(result, list)
    assert len(result) == 1
    assert responses.assert_call_count(url, 3) is True


@responses.activate
def test_list_request_404(gl):
    url = "http://localhost/api/v4/not_there"
    responses.add(
        method=responses.GET,
        url=url,
        json=[],
        status=404,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabHttpError):
        gl.http_list("/not_there")
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_list_request_invalid_data(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.GET,
        url=url,
        body='["name": "project1"]',
        content_type="application/json",
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabParsingError):
        gl.http_list("/projects")
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_post_request(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.POST,
        url=url,
        json={"name": "project1"},
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    result = gl.http_post("/projects")
    assert isinstance(result, dict)
    assert result["name"] == "project1"
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_post_request_404(gl):
    url = "http://localhost/api/v4/not_there"
    responses.add(
        method=responses.POST,
        url=url,
        json=[],
        status=404,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabHttpError):
        gl.http_post("/not_there")
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_post_request_invalid_data(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.POST,
        url=url,
        content_type="application/json",
        body='["name": "project1"]',
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabParsingError):
        gl.http_post("/projects")
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_put_request(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.PUT,
        url=url,
        json={"name": "project1"},
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    result = gl.http_put("/projects")
    assert isinstance(result, dict)
    assert result["name"] == "project1"
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_put_request_404(gl):
    url = "http://localhost/api/v4/not_there"
    responses.add(
        method=responses.PUT,
        url=url,
        json=[],
        status=404,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabHttpError):
        gl.http_put("/not_there")
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_put_request_invalid_data(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.PUT,
        url=url,
        body='["name": "project1"]',
        content_type="application/json",
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabParsingError):
        gl.http_put("/projects")
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_delete_request(gl):
    url = "http://localhost/api/v4/projects"
    responses.add(
        method=responses.DELETE,
        url=url,
        json=True,
        status=200,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    result = gl.http_delete("/projects")
    assert isinstance(result, requests.Response)
    assert result.json() is True
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_delete_request_404(gl):
    url = "http://localhost/api/v4/not_there"
    responses.add(
        method=responses.DELETE,
        url=url,
        json=[],
        status=404,
        match=MATCH_EMPTY_QUERY_PARAMS,
    )

    with pytest.raises(GitlabHttpError):
        gl.http_delete("/not_there")
    assert responses.assert_call_count(url, 1) is True


@responses.activate
def test_array_type_request(gl):
    url = "http://localhost/api/v4/projects"
    params = "array_var[]=1&array_var[]=2&array_var[]=3"
    full_url = f"{url}?array_var%5B%5D=1&array_var%5B%5D=2&array_var%5B%5D=3"
    responses.add(
        method=responses.GET,
        url=url,
        json={"name": "project1"},
        status=200,
        match=[responses.matchers.query_string_matcher(params)],
    )

    gl.http_get("/projects", array_var=gitlab.types.ArrayAttribute([1, 2, 3]))
    assert responses.assert_call_count(full_url, 1) is True
