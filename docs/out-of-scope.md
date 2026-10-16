# What's out of scope

DecisionTrace **records and recalls**. It deliberately does not:

- **Enforce anything.** No gateway, proxy or policy engine. Your code, your permission rules
  and your policy engine decide; DecisionTrace records what they decided. (Authority
  Envelope checks are recorded, not enforced.)
- **Run as a hosted service** or sync between machines.
- **Score trust or route work** (TrustRank, WorkRank).
- **Build a team-wide decision graph**, auto-approve from precedent, or report on how a
  company's decisions are trending (cost, compounding, approvals per 100 decisions).

Those need many people's traces over time; they are [Liquicent](https://liquicent.com)'s
products — *DecisionTrace records. Valence reveals. Liquicent learns.* The local store and
open schema are designed so they can read what you record here, if you choose.
