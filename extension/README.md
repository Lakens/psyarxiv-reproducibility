# Metacheck reports for PsyArXiv: browser extension

On a PsyArXiv preprint page, this extension adds a button in the bottom right corner that opens Metacheck's report on that preprint, when https://lakens.github.io/psyarxiv_metacheck/ has one. Without a report, nothing is shown.

- Pages: `osf.io/preprints/psyarxiv/<id>`, `next.psyarxiv.org/preprints/<id>`, and OSF's short links `osf.io/<id>`; the id with or without its version ending (`jc6rp_v1` or `jc6rp`).
- The button opens the report on that version. When only another version was checked, it opens the newest version checked and says which ("Metacheck report (version 2)").
- Green as the site's links; grey when none of the Metacheck modules applied to the preprint. The × hides it on that page.
- It reads the site's `data/index.json` once per page. It asks for no permissions beyond running on those two sites, and sends nothing else anywhere.

Files: `manifest.json` (the description browsers read), `content.js` (all the code), `icons/` (made from `images/logo.png`).

## Installing it yourself, without a store

Vivaldi, Chrome, Edge, Brave, Opera:
1. Open `vivaldi://extensions` (Chrome: `chrome://extensions`, Edge: `edge://extensions`).
2. Switch on "Developer mode".
3. Choose "Load unpacked" and select this `extension` folder.
After a change to the files, press the reload arrow on the extension's card. Chrome-based browsers mention the Firefox setting in `manifest.json` (`browser_specific_settings`) as an unrecognised key; that is harmless.

Firefox: open `about:debugging#/runtime/this-firefox`, choose "Load Temporary Add-on…", and select `manifest.json`. Firefox removes it again when it closes; a lasting installation needs the extension signed through addons.mozilla.org.

## Publishing it

- Chrome Web Store (also installs in Vivaldi, Edge, Brave, Opera): a one-time developer registration fee; each version is reviewed. Upload a .zip of the contents of this folder (`manifest.json` at the top of the .zip).
- Firefox Add-ons (addons.mozilla.org): free; each version is reviewed. Same .zip. The id in `manifest.json` (`metacheck-psyarxiv@lakens.github.io`) identifies it there.
- Raise `version` in `manifest.json` for every new upload.

## Testing the code

`content.js` also runs under Node for its address and lookup functions, without a page:

```
node -e "const x = require('./extension/content.js'); console.log(x.preprintId('https://osf.io/preprints/psyarxiv/jc6rp_v1'))"
```
