#!/usr/bin/env bash
# Builds a signed InboxOnly.ipa with your Apple Developer account and publishes
# it to this repo's GitHub Pages install page, so registered iPhones can
# install it by tapping a link.
#
#   TEAM_ID=ABCDE12345 ./scripts/publish.sh
#
# Needs a Mac with Xcode signed in to your developer account (Xcode →
# Settings → Accounts) and the iPhone registered as a device. The build is
# valid for as long as its provisioning profile (one year on a paid account).
# Run it again to renew, or after registering another iPhone.
set -euo pipefail
cd "$(dirname "$0")/.."

TEAM_ID="${TEAM_ID:-}"
if [ -z "$TEAM_ID" ]; then
  echo "Set TEAM_ID to your 10-character Apple Team ID" >&2
  echo "(developer.apple.com/account → Membership details), for example:" >&2
  echo "  TEAM_ID=ABCDE12345 ./scripts/publish.sh" >&2
  exit 1
fi

# https://github.com/owner/repo(.git) or git@github.com:owner/repo(.git)
SLUG=$(git remote get-url origin | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')
OWNER=$(echo "${SLUG%%/*}" | tr '[:upper:]' '[:lower:]')
PAGES="https://$OWNER.github.io/${SLUG#*/}"

command -v xcodegen >/dev/null || { echo "Installing XcodeGen…"; brew install xcodegen; }
(cd ios && xcodegen generate --quiet)

OUT=build/publish
rm -rf "$OUT"
mkdir -p "$OUT"

echo "Archiving…"
xcodebuild archive -quiet \
  -project ios/InboxOnly.xcodeproj -scheme InboxOnly -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$OUT/InboxOnly.xcarchive" \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="$TEAM_ID" CURRENT_PROJECT_VERSION="$(date +%Y%m%d%H%M)" \
  ${BUNDLE_ID_PREFIX:+"BUNDLE_ID_PREFIX=$BUNDLE_ID_PREFIX"}

# Xcode 15.3 renamed the "ad-hoc" export method to "release-testing".
XCODE_MAJOR=$(xcodebuild -version | awk 'NR==1 { split($2, v, "."); print v[1] }')
METHOD=ad-hoc
[ "$XCODE_MAJOR" -ge 16 ] && METHOD=release-testing

cat > "$OUT/ExportOptions.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>$METHOD</string>
  <key>teamID</key><string>$TEAM_ID</string>
  <key>signingStyle</key><string>automatic</string>
  <key>thinning</key><string>&lt;none&gt;</string>
</dict>
</plist>
EOF

echo "Signing for registered devices…"
xcodebuild -exportArchive -quiet \
  -archivePath "$OUT/InboxOnly.xcarchive" -exportPath "$OUT" \
  -exportOptionsPlist "$OUT/ExportOptions.plist" -allowProvisioningUpdates

IPA=$(ls "$OUT"/*.ipa | head -n 1)
INFO="$OUT/InboxOnly.xcarchive/Info.plist"
BUNDLE_ID=$(/usr/libexec/PlistBuddy -c 'Print :ApplicationProperties:CFBundleIdentifier' "$INFO")
VERSION=$(/usr/libexec/PlistBuddy -c 'Print :ApplicationProperties:CFBundleShortVersionString' "$INFO")

# The provisioning profile decides how long the app runs and on which iPhones.
unzip -q "$IPA" -d "$OUT/ipa"
security cms -D -i "$OUT"/ipa/Payload/*.app/embedded.mobileprovision > "$OUT/profile.plist"
EXPIRES=$(plutil -extract ExpirationDate raw -o - "$OUT/profile.plist")
DEVICES=$(plutil -extract ProvisionedDevices raw -o - "$OUT/profile.plist")

cp "$IPA" docs/InboxOnly.ipa

cat > docs/manifest.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>items</key>
  <array>
    <dict>
      <key>assets</key>
      <array>
        <dict><key>kind</key><string>software-package</string><key>url</key><string>$PAGES/InboxOnly.ipa</string></dict>
        <dict><key>kind</key><string>display-image</string><key>url</key><string>$PAGES/icon-57.png</string></dict>
        <dict><key>kind</key><string>full-size-image</string><key>url</key><string>$PAGES/icon-512.png</string></dict>
      </array>
      <key>metadata</key>
      <dict>
        <key>bundle-identifier</key><string>$BUNDLE_ID</string>
        <key>bundle-version</key><string>$VERSION</string>
        <key>kind</key><string>software</string>
        <key>title</key><string>Inbox</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>
EOF

cat > docs/release.json <<EOF
{ "version": "$VERSION", "built": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "expires": "$EXPIRES", "devices": $DEVICES }
EOF

git add docs/InboxOnly.ipa docs/manifest.plist docs/release.json
git commit -m "Publish Inbox $VERSION (valid until ${EXPIRES%%T*})"
git push

if command -v gh >/dev/null; then
  gh release create "v$VERSION-$(date +%Y%m%d%H%M)" "docs/InboxOnly.ipa" \
    --title "Inbox $VERSION" \
    --notes "Install on iPhone: open $PAGES/ in Safari and tap Install. Valid until ${EXPIRES%%T*} on $DEVICES registered device(s)."
fi

echo
echo "Published. Signed for $DEVICES device(s), valid until ${EXPIRES%%T*}."
echo "On the iPhone, open $PAGES/ in Safari and tap Install."
echo "(GitHub Pages takes a minute or two to pick up the new build.)"
