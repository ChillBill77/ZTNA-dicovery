import type { GroupBy } from "../store/filterStore";

interface Props {
  value: GroupBy;
  onChange: (next: GroupBy) => void;
}

const OPTIONS: Array<{ value: GroupBy; label: string }> = [
  { value: "group", label: "Groups" },
  { value: "user", label: "Users" },
  { value: "src_ip", label: "Source IPs" },
];

/** Three-way pill toggle for the Sankey left column. */
export default function LeftColumnModeToggle({
  value,
  onChange,
}: Props): JSX.Element {
  return (
    <div
      role="radiogroup"
      aria-label="Left-column grouping"
      className="inline-flex rounded bg-slate-800 p-1 text-sm"
      data-testid="left-column-mode-toggle"
    >
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          role="radio"
          aria-checked={value === opt.value}
          data-testid={`mode-${opt.value}`}
          className={`px-3 py-1 rounded ${
            value === opt.value
              ? "bg-okabe-sky text-black"
              : "text-slate-300 hover:text-slate-100"
          }`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
