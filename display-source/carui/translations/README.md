# Sailplay translations

English source strings are the fallback. Catalogs cover Simplified Chinese (`zh_CN`), Traditional Chinese (`zh_TW`), German (`de`), French (`fr`) and Russian (`ru`). Chinese locales for Taiwan and Hong Kong use the Traditional Chinese catalog; other Chinese locales use Simplified Chinese. Other regions fall back to their language catalog, then English.

Both QML views use the `Sailplay` translation context; controller error messages use `CarUiController`. Preserve `%1` and `%2` placeholders and intentional line breaks. Do not translate protocol identifiers, desktop app IDs or the compositor window title.

Update a catalog with Qt Linguist or edit its `.ts` file. `rpm/build-arm.sh` compiles every catalog with `lrelease`; `rpm/make-rpm.sh` packages the resulting `.qm` files in `/opt/sailplay/carui/translations`. Run the ARM build after changing translations to avoid packaging stale catalogs.
