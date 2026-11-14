# Contributing

Thanks for helping. ECG Source List is open core (see [`LICENSING.md`](LICENSING.md)): this
repository is licensed under the GNU AGPL-3.0-only, and the copyright holder also offers
commercial licenses. To keep that possible, contributions are accepted on these terms.

## Contributor license terms

By submitting a contribution (a pull request, patch, or other material) to this
repository, you agree that:

1. **It is yours to give.** You wrote it, or you have the right to submit it, and it isn't
   subject to terms that conflict with these. If your employer has rights to your work, you
   have their permission.
2. **It is licensed under the AGPL-3.0-only**, like the rest of the repository.
3. **You also grant Matthew Kelly** (the copyright holder) a perpetual, worldwide,
   non-exclusive, royalty-free, irrevocable license to use, modify, sublicense and
   distribute your contribution under any license terms, including proprietary ones. This
   also covers any patent claims you hold that your contribution necessarily infringes. You
   keep the copyright in your contribution.
4. **There is no warranty** from you, and no obligation for anyone to accept your
   contribution.

Add this line to each commit (`git commit -s` does it) to confirm:

```
Signed-off-by: Your Name <you@example.com>
```

## Practicalities

- Each source file starts with `SPDX-License-Identifier: AGPL-3.0-only` and the copyright
  line; keep them on files you add.
- New dependencies must be permissively licensed (MIT, BSD, Apache-2.0, ISC, Zlib, or
  file-level MPL-2.0). Add them to `docs/THIRD_PARTY_LICENSES.md`.
- Run the tests (`pytest core/tests desktop/engine/tests`), `ruff check` and `npm run build` in
  `web/`. The *Checks* workflow runs the same on every push.
