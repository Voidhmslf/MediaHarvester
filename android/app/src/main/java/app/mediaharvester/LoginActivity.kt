package app.mediaharvester

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/** Встроенный браузер для входа в сервис: после «Готово» cookies сохраняются для загрузок. */
class LoginActivity : Activity() {
    private lateinit var site: Site
    private lateinit var web: WebView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        site = SITES.firstOrNull { it.id == intent.getStringExtra(EXTRA_SITE) } ?: run { finish(); return }

        val dark = (resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK) ==
            android.content.res.Configuration.UI_MODE_NIGHT_YES
        val bg = if (dark) Color.parseColor("#1A1A1D") else Color.WHITE
        val fg = if (dark) Color.parseColor("#F2F2F2") else Color.parseColor("#1A1A1A")
        val accent = Color.parseColor("#D9480F")

        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            // Без «; wv» сайты реже считают браузер встроенным и не блокируют вход
            settings.userAgentString = settings.userAgentString.replace("; wv", "")
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
            webViewClient = WebViewClient()
            loadUrl(site.loginUrl)
        }

        val title = TextView(this).apply {
            text = "Вход в ${site.name}"
            setTextColor(fg)
            textSize = 17f
        }
        val cancel = Button(this).apply {
            text = "Отмена"
            setOnClickListener { finish() }
        }
        val done = Button(this).apply {
            text = "Готово"
            setTextColor(Color.WHITE)
            setBackgroundColor(accent)
            setOnClickListener { finishLogin() }
        }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(bg)
            setPadding(32, 24, 32, 24)
            addView(title, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(cancel)
            addView(done, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginStart = 16 })
        }
        val hint = TextView(this).apply {
            text = "Войдите в аккаунт, затем нажмите «Готово». Пароль приложению не передаётся: сохраняется только сессия."
            setTextColor(fg)
            setBackgroundColor(bg)
            textSize = 12f
            setPadding(32, 0, 32, 16)
        }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(bg)
            fitsSystemWindows = true
            addView(bar)
            addView(hint)
            addView(web, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        })
    }

    private fun finishLogin() {
        val ok = Cookies.capture(this, site)
        setResult(RESULT_OK, Intent().putExtra(EXTRA_MESSAGE,
            if (ok) "Вход в ${site.name} сохранён" else "Вход в ${site.name} не обнаружен: сначала войдите в аккаунт"))
        finish()
    }

    @Deprecated("Back ведёт по истории страниц, пока она есть")
    override fun onBackPressed() {
        if (::web.isInitialized && web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        if (::web.isInitialized) web.destroy()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_SITE = "site"
        const val EXTRA_MESSAGE = "message"
    }
}
