import { createHash } from "node:crypto";
import {
  lstatSync,
  readdirSync,
  readlinkSync,
  realpathSync,
  openSync,
  closeSync,
  fstatSync,
  readSync,
  constants,
} from "node:fs";
import path from "node:path";

const digest = (bytes: Buffer | string) => createHash("sha256").update(bytes).digest("hex");
const unicode = (value: string) => {
  if (Buffer.from(value, "utf8").toString("utf8") !== value)
    throw new Error("Invalid bundle Unicode");
  return value;
};
const order = (a: string, b: string) => {
  const x = Array.from(a, (c) => c.codePointAt(0)!);
  const y = Array.from(b, (c) => c.codePointAt(0)!);
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    if (x[i] !== y[i]) return x[i]! - y[i]!;
  }
  return x.length - y.length;
};

/** Hash a stable regular file without following a substituted symlink. */
export function stableFileSha256(file: string): string {
  const fd = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const before = fstatSync(fd, { bigint: true });
    if (!before.isFile()) throw new Error("Expected regular artifact file");
    const hash = createHash("sha256");
    const buffer = Buffer.alloc(1024 * 1024);
    let total = 0n;
    for (;;) {
      const count = readSync(fd, buffer, 0, buffer.length, null);
      if (!count) break;
      total += BigInt(count);
      hash.update(buffer.subarray(0, count));
    }
    const after = fstatSync(fd, { bigint: true });
    const current = lstatSync(file, { bigint: true });
    for (const key of ["dev", "ino", "mode", "size", "mtimeNs", "ctimeNs"] as const) {
      if (before[key] !== after[key] || before[key] !== current[key])
        throw new Error("Unstable artifact file");
    }
    if (total !== before.size) throw new Error("Unstable artifact size");
    return hash.digest("hex");
  } finally {
    closeSync(fd);
  }
}

/** Contract v1: whole on-disk bundle identity, never loaded-code identity. */
export function bundleSha256(root: string): string {
  const canonical = realpathSync(root);
  if (!lstatSync(canonical).isDirectory()) throw new Error("Bundle root must be a directory");
  const observations: Array<{ file: string; stat: string }> = [];
  const rows: Array<{ name: string; row: unknown[] }> = [];
  const stamp = (file: string) => {
    const s = lstatSync(file, { bigint: true });
    return [s.dev, s.ino, s.mode, s.size, s.mtimeNs, s.ctimeNs].join(":");
  };
  function visit(file: string, name: string): void {
    const before = stamp(file);
    const s = lstatSync(file);
    const mode = s.mode & 0o777;
    if (s.isSymbolicLink()) {
      const rawTarget = readlinkSync(file, { encoding: "buffer" });
      const target = unicode(rawTarget.toString("utf8"));
      if (!Buffer.from(target, "utf8").equals(rawTarget))
        throw new Error("Invalid symlink Unicode");
      const resolved = realpathSync(file);
      const relative = path.relative(canonical, resolved);
      if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
        throw new Error("Bundle symlink escapes artifact");
      }
      rows.push({ name, row: ["l", name, mode, target] });
    } else if (s.isDirectory()) {
      if (name) rows.push({ name, row: ["d", name, mode] });
      for (const raw of readdirSync(file, { encoding: "buffer" })) {
        const child = unicode(raw.toString("utf8"));
        if (!Buffer.from(child, "utf8").equals(raw)) throw new Error("Invalid bundle filename");
        visit(path.join(file, child), name ? `${name}/${child}` : child);
      }
    } else if (s.isFile()) {
      rows.push({ name, row: ["f", name, mode, s.size, stableFileSha256(file)] });
    } else {
      throw new Error("Unsupported bundle entry");
    }
    if (before !== stamp(file)) throw new Error("Unstable bundle entry");
    observations.push({ file, stat: before });
  }
  visit(canonical, "");
  for (const observation of observations) {
    if (stamp(observation.file) !== observation.stat) throw new Error("Unstable bundle snapshot");
  }
  if (realpathSync(root) !== canonical) throw new Error("Bundle root changed");
  return digest(
    rows
      .sort((a, b) => order(a.name, b.name))
      .map(({ row }) => `${JSON.stringify(row)}\n`)
      .join(""),
  );
}
