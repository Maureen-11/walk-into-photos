export type CollisionBox = {
  box_id: string;
  bounds: { x?: number[]; z?: number[] };
  label?: string;
};

export type MovementContract = {
  bounds: Record<string, number[]>;
  collision_radius?: number;
  collision_boxes?: CollisionBox[];
};

export function directionForYaw(yaw: number, forward: number, sideways: number) {
  // Three.js cameras look down local -Z. The vector is derived from the
  // camera's horizontal heading, so W always follows what the user sees.
  return {
    x: -Math.sin(yaw) * forward + Math.cos(yaw) * sideways,
    z: -Math.cos(yaw) * forward - Math.sin(yaw) * sideways,
  };
}

function containsExpandedBox(x: number, z: number, box: CollisionBox, radius: number) {
  const xBounds = box.bounds.x;
  const zBounds = box.bounds.z;
  if (!xBounds || !zBounds || xBounds.length !== 2 || zBounds.length !== 2) return false;
  return x >= xBounds[0] - radius && x <= xBounds[1] + radius
    && z >= zBounds[0] - radius && z <= zBounds[1] + radius;
}

export function resolveHorizontalMovement(
  position: [number, number, number],
  delta: { x: number; z: number },
  movement: MovementContract,
): [number, number, number] {
  const radius = Math.max(0, movement.collision_radius ?? 0);
  const maxStep = 0.12;
  const steps = Math.max(1, Math.ceil(Math.max(Math.abs(delta.x), Math.abs(delta.z)) / maxStep));
  let x = position[0];
  let z = position[2];
  const stepX = delta.x / steps;
  const stepZ = delta.z / steps;
  const collides = (candidateX: number, candidateZ: number) => (movement.collision_boxes ?? [])
    .some((box) => containsExpandedBox(candidateX, candidateZ, box, radius));

  for (let index = 0; index < steps; index += 1) {
    const nextX = x + stepX;
    const nextZ = z + stepZ;
    if (!collides(nextX, nextZ)) {
      x = nextX;
      z = nextZ;
      continue;
    }
    // Try each axis independently so the avatar slides along a wall or the
    // side of a piece of furniture instead of stopping on both axes.
    if (!collides(nextX, z)) x = nextX;
    if (!collides(x, nextZ)) z = nextZ;
  }

  const xBounds = movement.bounds.x;
  const zBounds = movement.bounds.z;
  if (xBounds?.length === 2) x = Math.max(xBounds[0], Math.min(xBounds[1], x));
  if (zBounds?.length === 2) z = Math.max(zBounds[0], Math.min(zBounds[1], z));
  return [x, position[1], z];
}
