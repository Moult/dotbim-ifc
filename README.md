# dotbim-ifc

## Purpose

Converts IFC to dotbim.

## Prerequirements

You need to install dotbimpy library (version >= 0.1.0) (https://github.com/paireks/dotbimpy):

```cmd
pip install dotbimpy
```

You also need IfcOpenShell 0.7.0 installed. You can get it from here: https://github.com/IfcOpenBot/IfcOpenShell/commit/883b8a523c63027f2f6c91650385d47edba5521b#commitcomment-65879927
Place this folder in your project where this script is located.

## How to use it

```python
ifc = ifcopenshell.open("foobar.ifc")
ifc2dotbim = Ifc2Dotbim(ifc)
ifc2dotbim.execute()
ifc2dotbim.write("foobar.bim")
```




