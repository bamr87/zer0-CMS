+++
title = "TOML constructs the reader guesses at"
description = "An array of tables read as a plain table, and a literal string it does not support."
date = "2026-02-05"
slug = "toml-array-tables"
layout = "post"
excerpt = '''
a literal string over two lines
'''
[[authors]]
name = "First"
[[authors]]
name = "Second"
+++

Every entry after the first overwrites the one before it.
