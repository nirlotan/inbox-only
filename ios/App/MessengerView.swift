import SafariServices
import SwiftUI
import WebKit

struct MessengerView: UIViewRepresentable {
    static let home = URL(string: "https://www.instagram.com/direct/inbox/")!

    /// extension/inbox-only.user.js, bundled into the app as a resource.
    private static let blockingScript: String? = Bundle.main
        .url(forResource: "inbox-only.user", withExtension: "js")
        .flatMap { try? String(contentsOf: $0, encoding: .utf8) }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default() // keeps you signed in between launches
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = .all
        // Look like Safari so Instagram serves its full mobile site.
        config.applicationNameForUserAgent = "Version/18.0 Mobile/15E148 Safari/604.1"

        if let source = Self.blockingScript {
            config.userContentController.addUserScript(
                WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true)
            )
        } else {
            assertionFailure("inbox-only.user.js is missing from the app bundle")
        }

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true // swipe back from a chat
        webView.allowsLinkPreview = false
        webView.isOpaque = false
        webView.backgroundColor = .systemBackground
        webView.scrollView.backgroundColor = .systemBackground
        webView.load(URLRequest(url: Self.home))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        // MARK: Navigation

        func webView(
            _ webView: WKWebView,
            decidePolicyFor action: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = action.request.url, action.targetFrame?.isMainFrame != false else {
                return decisionHandler(.allow) // subframes: login helpers, captchas
            }
            switch Self.route(url) {
            case .stay:
                decisionHandler(.allow)
            case .open(let external):
                decisionHandler(.cancel)
                open(external, from: webView)
            case .drop:
                decisionHandler(.cancel)
            }
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()
        }

        // Links with target="_blank".
        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for action: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            if let url = action.request.url {
                switch Self.route(url) {
                case .stay: webView.load(action.request)
                case .open(let external): open(external, from: webView)
                case .drop: break
                }
            }
            return nil
        }

        enum Route { case stay, open(URL), drop }

        static func route(_ url: URL) -> Route {
            guard let scheme = url.scheme?.lowercased() else { return .stay }
            if ["about", "blob", "data"].contains(scheme) { return .stay }
            // Never hand off to the real Instagram app: that's where the reels are.
            if scheme.hasPrefix("instagram") || scheme.hasPrefix("fb") { return .drop }
            guard scheme == "http" || scheme == "https" else { return .open(url) }

            let host = url.host?.lowercased() ?? ""
            // Instagram's outbound link shim: open the real destination instead.
            if host == "l.instagram.com",
               let target = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                   .queryItems?.first(where: { $0.name == "u" })?.value,
               let targetURL = URL(string: target) {
                return .open(targetURL)
            }
            let inApp = ["instagram.com", "facebook.com", "fbcdn.net", "cdninstagram.com"]
                .contains { host == $0 || host.hasSuffix("." + $0) }
            return inApp ? .stay : .open(url)
        }

        private func open(_ url: URL, from webView: WKWebView) {
            guard url.scheme == "http" || url.scheme == "https" else {
                UIApplication.shared.open(url)
                return
            }
            let safari = SFSafariViewController(url: url)
            safari.dismissButtonStyle = .close
            topController(of: webView)?.present(safari, animated: true)
        }

        // MARK: JavaScript dialogs (e.g. "Unsend message?")

        func webView(
            _ webView: WKWebView,
            runJavaScriptAlertPanelWithMessage message: String,
            initiatedByFrame frame: WKFrameInfo,
            completionHandler: @escaping () -> Void
        ) {
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
            present(alert, from: webView, orElse: completionHandler)
        }

        func webView(
            _ webView: WKWebView,
            runJavaScriptConfirmPanelWithMessage message: String,
            initiatedByFrame frame: WKFrameInfo,
            completionHandler: @escaping (Bool) -> Void
        ) {
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
            present(alert, from: webView) { completionHandler(false) }
        }

        private func present(_ alert: UIAlertController, from webView: WKWebView, orElse fallback: () -> Void) {
            guard let top = topController(of: webView) else { return fallback() }
            top.present(alert, animated: true)
        }

        private func topController(of view: UIView) -> UIViewController? {
            var top = view.window?.rootViewController
            while let presented = top?.presentedViewController { top = presented }
            return top
        }
    }
}
