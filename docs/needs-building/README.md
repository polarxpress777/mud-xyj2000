# needs-building

Problems that are worth solving and have **not yet been designed**.

Two documents define the current scope:

- **[PRD.md](PRD.md)** — what needs to exist, stated as problems and
  outcomes, with acceptance tests. No implementation prescribed.
- **[ARCHITECTURE-REVIEW.md](ARCHITECTURE-REVIEW.md)** — how the system
  is actually put together today, where the seams are wrong, and which
  of those the PRD items collide with.

Read the architecture review first if you intend to design any of it.
Several PRD items look independent and are not.

An item leaves this folder by acquiring a design, and moves to
[`../planned/`](../planned/).
