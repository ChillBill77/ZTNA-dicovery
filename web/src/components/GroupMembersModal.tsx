import { useEffect, useState } from "react";

interface GroupMembers {
  group_id: string;
  group_name: string;
  size: number;
  members: string[];
  next_cursor: string | null;
}

interface Props {
  groupId: string | null;
  onClose: () => void;
}

const PAGE_SIZE = 100;
const MAX_MEMBERS = 200;

/** Modal listing up to ``MAX_MEMBERS`` users in the selected group. */
export default function GroupMembersModal({
  groupId,
  onClose,
}: Props): JSX.Element | null {
  const [data, setData] = useState<GroupMembers | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!groupId) return;
    setData(null);
    setLoading(true);
    void fetch(
      `/api/groups/${encodeURIComponent(groupId)}?page_size=${PAGE_SIZE}`,
      { credentials: "include" },
    )
      .then(async (r) => {
        if (!r.ok) throw new Error(`groups failed: ${r.status}`);
        return (await r.json()) as GroupMembers;
      })
      .then(setData)
      .finally(() => setLoading(false));
  }, [groupId]);

  async function loadMore(): Promise<void> {
    if (!data?.next_cursor || data.members.length >= MAX_MEMBERS) return;
    setLoading(true);
    const r = await fetch(
      `/api/groups/${encodeURIComponent(data.group_id)}?page_size=${PAGE_SIZE}&cursor=${encodeURIComponent(data.next_cursor)}`,
      { credentials: "include" },
    );
    setLoading(false);
    if (!r.ok) return;
    const next = (await r.json()) as GroupMembers;
    setData({
      ...data,
      members: [...data.members, ...next.members].slice(0, MAX_MEMBERS),
      next_cursor: next.next_cursor,
    });
  }

  if (!groupId) return null;
  return (
    <div
      role="dialog"
      aria-label="Group members"
      data-testid="group-members-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="bg-slate-900 border border-slate-700 rounded shadow-xl w-[32rem] max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-4 py-2 border-b border-slate-700">
          <div>
            <div className="font-semibold">
              {data?.group_name ?? groupId}
            </div>
            {data && (
              <div className="text-xs text-slate-400">
                {data.size} members
                {data.size > MAX_MEMBERS &&
                  ` · showing first ${Math.min(data.members.length, MAX_MEMBERS)}`}
              </div>
            )}
          </div>
          <button
            data-testid="modal-close"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-100"
          >
            ✕
          </button>
        </header>
        <ul className="overflow-auto flex-1 divide-y divide-slate-800">
          {data?.members.map((m) => (
            <li
              key={m}
              data-testid="member-row"
              className="px-4 py-1 text-sm font-mono text-slate-200"
            >
              {m}
            </li>
          ))}
          {loading && <li className="px-4 py-2 text-slate-500">Loading…</li>}
        </ul>
        {data?.next_cursor && data.members.length < MAX_MEMBERS && (
          <footer className="border-t border-slate-700 p-2">
            <button
              onClick={loadMore}
              className="w-full px-3 py-1 rounded bg-slate-800 text-sm hover:bg-slate-700"
            >
              Load more
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}
