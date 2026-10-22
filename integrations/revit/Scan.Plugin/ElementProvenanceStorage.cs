using Autodesk.Revit.DB;
using Autodesk.Revit.DB.ExtensibleStorage;

namespace Scan.Revit.Plugin;

internal static class ElementProvenanceStorage
{
    private static readonly Guid SchemaId = new("2f4acdb7-4fe2-4dc1-9d9a-6ef8359d7701");
    private const string FieldName = "PayloadJson";

    public static void Attach(Element element, string payloadJson)
    {
        var schema = Schema.Lookup(SchemaId) ?? CreateSchema();
        var entity = new Entity(schema);
        entity.Set(FieldName, payloadJson);
        element.SetEntity(entity);
    }

    private static Schema CreateSchema()
    {
        var builder = new SchemaBuilder(SchemaId);
        builder.SetSchemaName("ScanStructuralProvenance");
        builder.SetDocumentation("SCAN source model, review state, dimensions and point evidence.");
        builder.SetVendorId("SCAN");
        builder.SetReadAccessLevel(AccessLevel.Public);
        builder.SetWriteAccessLevel(AccessLevel.Vendor);
        builder.AddSimpleField(FieldName, typeof(string));
        return builder.Finish();
    }
}
