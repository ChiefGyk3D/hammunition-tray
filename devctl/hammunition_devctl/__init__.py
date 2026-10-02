# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""hammunition-devctl: the device helper of the Hammunition suite.

``docs/contract.md`` in the repository is the interface; ``CONTRACT`` below is
its number and changes in the same commit as that file.
"""

CONTRACT = 1
"""The contract this helper implements. ``hammunition-devctl --version`` prints
it, and a front end compares it with the lowest it needs."""
