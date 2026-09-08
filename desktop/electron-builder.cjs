"use strict";
const signed = process.env.CLEANTAKE_SIGN === "true";

module.exports = {
  appId: "com.pavangupta352.cleantake",
  productName: "CleanTake",
  artifactName: "CleanTake-${version}-${os}-${arch}.${ext}",
  directories: { output: "../dist/native", buildResources: "resources" },
  files: ["main.cjs", "lib/**", "launch.html", "launch.css", "resources/icon.png", "resources/LUCIDE-LICENSE", "package.json"],
  extraResources: [
    { from: "../build/native/runtime/cleantake-runtime", to: "backend" },
    { from: "../LICENSE", to: "LICENSE" },
    { from: "../THIRD_PARTY_NOTICES.md", to: "THIRD_PARTY_NOTICES.md" },
  ],
  asar: true,
  npmRebuild: false,
  publish: null,
  mac: {
    target: [{ target: "dmg", arch: [process.arch] }],
    category: "public.app-category.music",
    minimumSystemVersion: "14.0",
    hardenedRuntime: signed,
    ...(signed ? {} : { identity: "-" }),
    notarize: signed,
    entitlements: "resources/entitlements.mac.plist",
    entitlementsInherit: "resources/entitlements.mac.plist",
    extendInfo: { NSHumanReadableCopyright: "Copyright © 2026 Pavan Gupta. Components retain their respective licenses." },
  },
  dmg: { title: "CleanTake ${version}" },
  win: { target: [{ target: "nsis", arch: [process.arch] }] },
  nsis: { oneClick: true, perMachine: false, packElevateHelper: false, runAfterFinish: true, createDesktopShortcut: true, createStartMenuShortcut: true, deleteAppDataOnUninstall: false },
  linux: { executableName: "cleantake", category: "AudioVideo;Audio;AudioVideoEditing", target: [{ target: "deb", arch: [process.arch] }, { target: "tar.xz", arch: [process.arch] }], synopsis: "Recover dialogue from your backup recordings" },
  deb: { packageName: "cleantake", depends: ["libgtk-3-0", "libnotify4", "libnss3", "libxss1", "libxtst6", "xdg-utils", "libatspi2.0-0", "libuuid1", "libsecret-1-0", "libasound2 | libasound2t64", "libgbm1", "libdrm2"] },
};
