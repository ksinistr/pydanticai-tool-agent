from app.bot.formatting import render_telegram_html


def test_render_telegram_html_formats_basic_markdown() -> None:
    text = "**Bold**\n- item\n`code`\n[site](https://example.com)"

    assert render_telegram_html(text) == (
        '<b>Bold</b>\n- item\n<code>code</code>\n<a href="https://example.com">site</a>'
    )


def test_render_telegram_html_escapes_non_markdown_html() -> None:
    assert render_telegram_html("<b>unsafe</b> & text") == "&lt;b&gt;unsafe&lt;/b&gt; &amp; text"
