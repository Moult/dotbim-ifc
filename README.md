# dotbim-ifc

Converts to and from IFC and Dotbim.

Going to ...

```python
ifc = ifcopenshell.open("foobar.ifc")
ifc2dotbim = Ifc2Dotbim(ifc)
ifc2dotbim.execute()
ifc2dotbim.write("foobar.bim")
```

Coming from ...

```python
dotbim = dotbimpy.File.read("foobar.bim")
dotbim2ifc = Dotbim2Ifc(dotbim)
dotbim2ifc.execute()
dotbim2ifc.write("foobar.ifc")
```
