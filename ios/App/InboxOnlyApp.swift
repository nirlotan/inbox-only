import SwiftUI

/// The app is the messenger: it opens straight into your Instagram inbox in a
/// full-screen web view running the same blocking script as the Safari
/// extension. The extension ships inside this app for use in Safari itself.
@main
struct InboxOnlyApp: App {
    var body: some Scene {
        WindowGroup {
            MessengerView()
                // Let the page handle the keyboard the way Safari does.
                .ignoresSafeArea(.keyboard)
                .background(Color(.systemBackground).ignoresSafeArea())
        }
    }
}
