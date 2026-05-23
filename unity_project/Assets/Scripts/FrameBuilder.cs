using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// Editor utility to auto-build a 2D frame structure for XuanwuAI simulation.
/// Run BuildFrame() from the Unity Editor context menu.
///
/// The frame is built with:
///   - Columns (vertical): Rigidbody + ConfigurableJoint connections
///   - Beams (horizontal): Rigidbody + ConfigurableJoint connections
///   - Ground plane for visual reference
///   - All elements tracked by SimulationController
///
/// Element ID order (0-based):
///   First: all columns (bottom-to-top, left-to-right)
///   Then: all beams (bottom-to-top, left-to-right)
/// </summary>
[RequireComponent(typeof(SimulationController))]
public class FrameBuilder : MonoBehaviour
{
    [Header("Frame Dimensions")]
    [SerializeField] private int spans = 2;
    [SerializeField] private int stories = 2;
    [SerializeField] private float spanLength = 6f;
    [SerializeField] private float storyHeight = 3f;

    [Header("Element Dimensions")]
    [SerializeField] private float columnWidth = 0.4f;
    [SerializeField] private float columnDepth = 0.4f;
    [SerializeField] private float beamHeight = 0.3f;
    [SerializeField] private float beamDepth = 0.3f;
    [SerializeField] private float elementMass = 500f;

    [Header("Materials")]
    [SerializeField] private Material columnMaterial;
    [SerializeField] private Material beamMaterial;
    [SerializeField] private Material groundMaterial;

    [ContextMenu("Build Frame")]
    public void BuildFrame()
    {
        // Clear existing structure
        var existingStructure = GameObject.Find("FrameStructure");
        if (existingStructure != null)
            DestroyImmediate(existingStructure);

        var structureRoot = new GameObject("FrameStructure");
        structureRoot.transform.SetParent(transform);

        var elements = new List<GameObject>();
        var nodePositions = new Dictionary<int, Vector3>();

        // Generate node grid
        int nodeId = 0;
        for (int row = 0; row <= stories; row++)
        {
            for (int col = 0; col <= spans; col++)
            {
                var pos = new Vector3(col * spanLength, row * storyHeight, 0);
                nodePositions[nodeId] = pos;
                nodeId++;

                // Ground marker at row 0
                if (row == 0)
                {
                    var marker = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    marker.name = $"Node_{nodeId - 1}_Base";
                    marker.transform.position = pos + Vector3.down * 0.15f;
                    marker.transform.localScale = new Vector3(0.5f, 0.3f, 0.5f);
                    marker.transform.SetParent(structureRoot.transform);
                    if (groundMaterial != null)
                        marker.GetComponent<Renderer>().material = groundMaterial;
                }
            }
        }

        // Build columns (vertical elements)
        int elementId = 0;
        for (int row = 0; row < stories; row++)
        {
            for (int col = 0; col <= spans; col++)
            {
                int bottomNodeId = row * (spans + 1) + col;
                int topNodeId = (row + 1) * (spans + 1) + col;

                var column = CreateStructuralElement(
                    $"Column_{elementId}",
                    nodePositions[bottomNodeId],
                    nodePositions[topNodeId],
                    new Vector3(columnWidth, storyHeight / 2f, columnDepth),
                    columnMaterial
                );
                column.transform.SetParent(structureRoot.transform);
                elements.Add(column);
                elementId++;
            }
        }

        // Build beams (horizontal elements)
        for (int row = 1; row <= stories; row++)
        {
            for (int col = 0; col < spans; col++)
            {
                int leftNodeId = row * (spans + 1) + col;
                int rightNodeId = row * (spans + 1) + col + 1;

                var beam = CreateStructuralElement(
                    $"Beam_{elementId}",
                    nodePositions[leftNodeId],
                    nodePositions[rightNodeId],
                    new Vector3(spanLength / 2f, beamHeight, beamDepth),
                    beamMaterial
                );
                beam.transform.SetParent(structureRoot.transform);
                elements.Add(beam);
                elementId++;
            }
        }

        // Connect elements with ConfigurableJoints at shared nodes
        ConnectJoints(elements, nodePositions);

        // Register with SimulationController
        var controller = GetComponent<SimulationController>();
        var elementsField = typeof(SimulationController).GetField("structuralElements",
            System.Reflection.BindingFlags.NonPublic |
            System.Reflection.BindingFlags.Instance);
        if (elementsField != null)
        {
            elementsField.SetValue(controller, elements);
        }

        Debug.Log($"[FrameBuilder] Built {spans}x{stories} frame: {elements.Count} elements, " +
                  $"{nodePositions.Count} nodes.");
    }

    private GameObject CreateStructuralElement(
        string name, Vector3 start, Vector3 end, Vector3 halfExtents, Material material)
    {
        var midPoint = (start + end) / 2f;
        var direction = (end - start).normalized;
        var length = Vector3.Distance(start, end);

        var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
        go.name = name;
        go.transform.position = midPoint;

        // Scale to fit between nodes
        var scale = halfExtents * 2f;
        scale.y = length;
        go.transform.localScale = scale;

        // Rotate to align with direction
        go.transform.up = direction;

        // Add Rigidbody
        var rb = go.AddComponent<Rigidbody>();
        rb.mass = elementMass;
        rb.drag = 0.1f;
        rb.angularDrag = 0.1f;

        // Assign material
        if (material != null)
            go.GetComponent<Renderer>().material = material;

        return go;
    }

    private void ConnectJoints(List<GameObject> elements, Dictionary<int, Vector3> nodePositions)
    {
        float jointRadius = 0.5f;

        // For each pair of elements near each other at a node, create joints
        for (int i = 0; i < elements.Count; i++)
        {
            for (int j = i + 1; j < elements.Count; j++)
            {
                var elemA = elements[i];
                var elemB = elements[j];
                if (elemA == null || elemB == null) continue;

                var dist = Vector3.Distance(elemA.transform.position, elemB.transform.position);
                if (dist < jointRadius * 2f)
                {
                    // Add fixed joints connecting elements at shared nodes
                    var joint = elemA.AddComponent<ConfigurableJoint>();
                    joint.connectedBody = elemB.GetComponent<Rigidbody>();
                    joint.anchor = Vector3.zero;
                    joint.connectedAnchor = elemB.transform.InverseTransformPoint(elemA.transform.position);
                    joint.xMotion = ConfigurableJointMotion.Locked;
                    joint.yMotion = ConfigurableJointMotion.Locked;
                    joint.zMotion = ConfigurableJointMotion.Locked;
                    joint.angularXMotion = ConfigurableJointMotion.Locked;
                    joint.angularYMotion = ConfigurableJointMotion.Locked;
                    joint.angularZMotion = ConfigurableJointMotion.Locked;
                    joint.enableCollision = false;
                    joint.breakForce = float.PositiveInfinity;
                    joint.breakTorque = float.PositiveInfinity;
                }
            }
        }
    }
}
