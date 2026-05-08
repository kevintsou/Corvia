"""COVIA LSP server package.

The server is exposed through the `covia-lsp` console script when the
optional [lsp] extras are installed. The conversion helpers in
`converter.py` have no pygls dependency so they can be tested in
isolation and reused if the server is ever swapped to a different LSP
runtime.
"""
