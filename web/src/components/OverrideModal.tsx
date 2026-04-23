import { useState } from "react";

import { useCreateApplication } from "../api/queries";
import { useDetailsStore } from "../store/detailsStore";

export default function OverrideModal({ onClose }: { onClose: () => void }) {
  const link = useDetailsStore((s) => s.selectedLink);
  const [name, setName] = useState(link ? link.dst.replace("app:", "") : "");
  const [cidr, setCidr] = useState("");
  const create = useCreateApplication();

  return (
    <div role="dialog" aria-modal className="fixed inset-0 bg-black/60 grid place-items-center">
      <form
        className="bg-slate-900 p-4 rounded space-y-2 w-96"
        onSubmit={async (e) => {
          e.preventDefault();
          await create.mutateAsync({ name, dst_cidr: cidr, priority: 150 });
          onClose();
        }}
      >
        <h3 className="font-semibold">Override label</h3>
        <label className="block">
          <span className="block text-slate-400 text-sm">Application name</span>
          <input
            className="w-full bg-slate-800 px-2 py-1 rounded"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="Application name"
          />
        </label>
        <label className="block">
          <span className="block text-slate-400 text-sm">Destination CIDR</span>
          <input
            className="w-full bg-slate-800 px-2 py-1 rounded"
            value={cidr}
            onChange={(e) => setCidr(e.target.value)}
            placeholder="10.100.0.0/16"
            aria-label="Destination CIDR"
          />
        </label>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="px-2 py-1 bg-slate-700 rounded"
            onClick={onClose}
          >Cancel</button>
          <button
            type="submit"
            className="px-2 py-1 bg-okabe-sky text-black rounded"
          >Save</button>
        </div>
      </form>
    </div>
  );
}
