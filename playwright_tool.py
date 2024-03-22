from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright, username: str, password: str) -> None:
    browser = playwright.firefox.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto("https://18comic.org/", timeout= 10000)
    page.get_by_role("button", name="我保證我已满18歲！").click()
    page.get_by_role("button", name="確定進入！").click()
    page.locator("#today_no_show").check()
    page.get_by_role("button", name="關閉").click()
    page.get_by_role("link", name="會員登入/註冊").click()
    page.get_by_label("用戶名:").click()
    page.get_by_label("用戶名:").fill(username)
    page.get_by_label("密碼:").click()
    page.get_by_label("密碼:").fill(password)
    page.get_by_role("button", name="登錄").click()
    page.wait_for_timeout(3000)

    cookies = context.cookies()
    ret_cookie = {}
    for cookie in cookies:
        if cookie['name'] == 'AVS':
            ret_cookie['AVS'] = cookie['value']

            
    page.close()

    # ---------------------
    context.close()
    browser.close()

    return ret_cookie

def login(username, password):
    """禁漫网站模拟登录，返回登录cookie

    如果出现人机验证，需要手动打开网站进行验证，之后
    都可以在这台机器上进行自动登录了
    """
    with sync_playwright() as playwright:
        cookie = run(playwright, username, password)
    return cookie