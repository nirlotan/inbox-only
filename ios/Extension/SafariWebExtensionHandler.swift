import SafariServices

/// Required entry point for a Safari Web Extension. All of the work happens in
/// the content script (inbox-only.user.js), so there are no native messages.
final class SafariWebExtensionHandler: NSObject, NSExtensionRequestHandling {
    func beginRequest(with context: NSExtensionContext) {
        context.completeRequest(returningItems: [], completionHandler: nil)
    }
}
