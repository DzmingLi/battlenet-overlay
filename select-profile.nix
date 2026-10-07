{ lib }:
profile: locale: region:
let
  installation = profile.installation or {};
  bundledLocales = lib.filter (tag: builtins.match "[a-z]{2}[A-Z]{2}" tag != null)
    (installation.storage.tags or []);
  variants = profile.locales or {};
  language = if region == "cn" && locale == null then "zhCN" else locale;
  selected = if region == "cn" then (profile.chinaLocales or {}).${language}
    or (throw "No verified China ${language} installation for ${profile.release.product or "this game"}.")
    else if locale == null || builtins.elem locale bundledLocales then profile
    else variants.${locale} or (throw "No verified ${locale} installation for ${profile.release.product or "this game"}.");
in assert lib.assertMsg (region != "cn" || (selected.release.region == "cn" && (selected.serviceRegion or null) == "cn"))
  "China requires an independently verified China distribution.";
assert lib.assertMsg ((locale == null && region != "cn") || (selected ? installation && (selected.installation.storage.completeInstallation or false)))
  "The selected language needs a complete object-hashed installation.";
selected
