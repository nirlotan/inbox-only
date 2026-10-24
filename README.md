# Inbox Only

Instagram as a plain messenger. You keep your DMs: chats, photos, voice
messages, message requests and new messages. Everything built to keep you
scrolling is blocked.

| Kept | Blocked |
|---|---|
| Inbox, chats, message requests, new message | Home feed, Explore, Reels tab |
| Photos and links in chats | Every video (it shows as a grey "Video blocked" box) |
| Voice messages | Reels shared in chats ("Reel hidden"), stories, profiles |
| Login, 2-factor, account settings | "Get the app" banners |

Tapping a profile, reel or story gives a small "Only messages here" toast
instead of opening it. If Instagram opens a feed or reel anyway, you're sent
straight back to the chat you were in.

---

## Install on iPhone

**Install page: <https://nirlotan.github.io/inbox-only/>**

Anyone with an iPhone can install it from that page through Apple's free
TestFlight app:

1. Get [TestFlight](https://apps.apple.com/app/testflight/id899247664) from the
   App Store.
2. Open the install page in Safari and tap **Install**. TestFlight opens: tap
   **Accept**, then **Install**.
3. Open **Inbox** and sign in to Instagram. You stay signed in.

TestFlight keeps the app up to date by itself.

## Publishing a build (maintainer, on a Mac)

One script does the whole release: it builds the app, signs it, uploads it to
TestFlight, fills in everything Apple asks for, creates the public link,
submits it for Apple's beta review and puts the link on the install page.

```bash
git clone https://github.com/nirlotan/inbox-only.git
cd inbox-only
./release.py
```

You need a Mac with Xcode, [Homebrew](https://brew.sh) and the paid Apple
Developer account. The first run asks for these (later runs remember them):

| It asks for | Where to get it |
|---|---|
| Team ID | [developer.apple.com/account](https://developer.apple.com/account) → Membership details |
| API key (`.p8` file, Key ID, Issuer ID) | The script opens App Store Connect → Users and Access → Integrations. Create a key with **Admin** access and download it. |
| The app record | Apple's API can't create apps, so the script opens App Store Connect and tells you exactly what to type into **+ → New App** (once). |
| Feedback email, your name and phone | For TestFlight and Apple's beta reviewer. |
| A demo Instagram account | Apple's reviewer signs in with it. Make a spare account for this. The password goes to Apple and isn't saved. |

What happens after it finishes:

- **You** can install right away: the script invites you to an internal
  TestFlight group, which doesn't wait for review. Check your email.
- **Everyone else** can install once Apple approves the build, usually within a
  day. Check with `./release.py status`.
- **Every 2-3 months**, run `./release.py` again. TestFlight builds expire after
  90 days; testers get the new build automatically.

If `git push` fails at the end, run `gh auth login` (after `brew install gh`)
and then `git push`. The TestFlight link works either way.

## Block videos in Safari too (optional)

The app carries a Safari Web Extension with the same blocking, so
instagram.com in Safari is video-free as well: **Settings → Apps → Safari →
Extensions → Inbox Only → Allow Extension**, and set **instagram.com** to
**Allow**.

## Other ways to install

- **No computer, no app:** install the free
  [Userscripts](https://apps.apple.com/app/userscripts/id1463298887) Safari
  extension, save [`extension/inbox-only.user.js`](extension/inbox-only.user.js)
  into its folder in the Files app, allow it on instagram.com, and use
  instagram.com/direct/inbox in Safari.
- **Straight from Xcode:** `cd ios && xcodegen generate && open InboxOnly.xcodeproj`,
  pick your team for both targets under **Signing & Capabilities**, select your
  iPhone and press **⌘R**. This needs Developer Mode on the iPhone.

---

## How it works

One file, `extension/inbox-only.user.js`, does all the blocking. It runs
unchanged in three places: the Safari extension (`extension/manifest.json`),
the app's web view, and the Userscripts app.

- **Pages:** only `/direct/…` and the login/account pages are allowed. Instagram
  is a single-page app, so the script checks the address four times a second
  and bounces anything else, back to your chat when it came from one.
- **Videos:** every `<video>` is invisible until its metadata loads. If it has
  a picture it's stopped, its source is removed and a "Video blocked" box takes
  its place. If it's audio only (a voice message) it plays normally.
- **Shared reels:** links to reels and cards with Instagram's reel icon get
  covered with "Reel hidden" and can't be opened.
- **App feel:** no page bounce or tap flashes, no zooming into the message box,
  Safari's bars tinted to match the page, and links to other sites open in a
  Safari sheet inside the app instead of leaving it.

The app (`ios/App`) is a full-screen web view on
`instagram.com/direct/inbox/` that injects the same script. It never hands
links to the real Instagram app.

```
extension/            the Safari Web Extension (also the userscript)
  inbox-only.user.js  all the blocking logic
  manifest.json
  icon-*.png
ios/
  project.yml         XcodeGen spec: app + extension targets
  App/                SwiftUI app: the messenger window
  Extension/          Safari extension entry point + Info.plist
.github/workflows/    builds an unsigned .ipa on GitHub's Macs (compile check)
release.py            builds, uploads and publishes to TestFlight (run on a Mac)
docs/                 the install page and privacy policy (GitHub Pages)
tools/make-icons.py   redraws the icons (python + Pillow)
```

## Limits

- **No push notifications.** This is Instagram's website in an app wrapper, so
  new messages show up while it's open, not when it's closed.
- **Instagram changes its site often.** Page and video blocking key off URLs and
  `<video>` elements, which are stable. Spotting reel cards inside chats relies
  on Instagram's English labels, so in other languages a shared reel may show
  its thumbnail, though it still won't open or play.
- The blocking script was tested against a mock inbox page in a browser, not
  against a signed-in Instagram account.
