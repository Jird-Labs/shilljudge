export default function Spinner({ size = 20 }) {
  return (
    <div
      className="inline-block rounded-full border-2 border-zinc-700 border-t-sky-400 animate-spin"
      style={{ width: size, height: size }}
    />
  );
}
