# Rule examples

##  message whitelist examples

The file `rules//message_whitelist.txt` now includes simple examples of commit-subject matching patterns.

### Examples
- `Fixes:` matches commits carrying a Fixes tag in the message body or parsed text flow.
- `Cc: stable@` matches commits explicitly marked for stable backport flow.
- `re:^(|net|can|mmc|ext4|crypto|security|thermal|watchdog|usb|pci):` matches a first component prefix before the first colon.
- `re:^net:\s*(phy|ipv4|ipv6|tls|xfrm):` matches some common nested net prefixes.
- `re:^:\s*[^:]+:` matches subjects like `: ipa: ...`.
- `re:^staging:\s*[^:]+:` matches staged-driver style prefixes like `staging: foo: ...`.

## V7.2 uploaded-content-derived whitelist
`rules//message_whitelist.txt` was regenerated from the uploaded `modules.txt`.
Each generated regex line targets the first token in a git commit subject, for example `re:^net(?:\s|:|$)` or `re:^mmc(?:\s|:|$)`.
The file also keeps a few nested-prefix examples such as `net: phy:` and `: ipa:` style subjects.
## V7.3 regeneration helper

You can now regenerate `rules//message_whitelist.txt` from a module-list style file with:

```sh
python3 tools/generate_message_whitelist.py   --module-list ./modules.txt   --output ./rules//message_whitelist.txt
```

Useful options:
- `--limit 80` limits how many first-token regex entries are emitted.
- `--output ...` lets you write to another whitelist file for experimentation.
