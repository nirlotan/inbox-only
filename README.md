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

The app is signed with a paid Apple Developer account for the iPhones
registered on it, and installs straight from that link. Each build works for a
year. There's a one-time setup on a Mac, then the iPhone part takes a minute.

### 1. One-time setup on your Mac (about 15 minutes)

1. **Register your iPhone with your developer account.**
   - Connect the iPhone to the Mac with a cable, open **Finder** and select the
     iPhone in the sidebar.
   - Click the grey line under its name (model, storage) until it shows
     **UDID**. Right-click it and choose **Copy UDID**.
   - Go to [developer.apple.com → Devices → +](https://developer.apple.com/account/resources/devices/add),
     choose **iOS**, give it a name, paste the UDID and press **Register**.
2. **Sign Xcode in to the same account:** Xcode → **Settings → Accounts → +
   → Apple ID**.
3. **Find your Team ID:** [developer.apple.com/account](https://developer.apple.com/account)
   → **Membership details → Team ID** (10 characters, like `ABCDE12345`).
4. **Build and publish.** In Terminal:

   ```bash
   git clone https://github.com/nirlotan/inbox-only.git
   cd inbox-only
   TEAM_ID=ABCDE12345 ./scripts/publish.sh
   ```

   The script builds the app, signs it for your registered iPhones, puts it on
   the install page and pushes to GitHub. It installs XcodeGen with Homebrew
   if needed. If `git push` asks you to sign in, run `gh auth login` first
   (or `brew install gh` if you don't have it).

### 2. On the iPhone (1 minute)

1. Open **<https://nirlotan.github.io/inbox-only/>** in **Safari**.
2. Tap **Install**, then **Install** again in the popup.
3. On your Home Screen, wait for the **Inbox** icon to finish loading, open it
   and sign in to Instagram. You stay signed in.

There's no Developer Mode or "trust this developer" step for this kind of
build.

### Renewing, and adding more iPhones

The install page shows the date the current build works until. Before then, or
whenever you register another iPhone, run `TEAM_ID=… ./scripts/publish.sh`
again and tap **Install** on the iPhone again. It installs over the old copy
and keeps you signed in.

### Optional: block videos in Safari too

The app carries a Safari Web Extension with the same blocking, so
instagram.com in Safari is video-free as well: **Settings → Apps → Safari →
Extensions → Inbox Only → Allow Extension**, and set **instagram.com** to
**Allow**.

### Other ways to install

- **No computer, no app:** install the free
  [Userscripts](https://apps.apple.com/app/userscripts/id1463298887) Safari
  extension, save [`extension/inbox-only.user.js`](extension/inbox-only.user.js)
  into its folder in the Files app, allow it on instagram.com, and use
  instagram.com/direct/inbox in Safari.
- **Straight from Xcode:** `cd ios && xcodegen generate && open InboxOnly.xcodeproj`,
  pick your team for both targets under **Signing & Capabilities**, select your
  iPhone and press **⌘R**. This needs Developer Mode on the iPhone.
- **Unsigned build:** every push to `main` runs **Actions → Build iOS app**,
  which builds an unsigned `.ipa` that tools like Sideloadly can sign and
  install.

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
scripts/publish.sh    signed build + install page (run on a Mac)
docs/                 the install page, served by GitHub Pages
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
