import { useAuth, type Role } from "./useAuth";

/** True when the authenticated caller holds ``required``. Falls back to false
 *  while ``me`` is still loading so role-gated UI doesn't flash visible. */
export function useRole(required: Role): boolean {
  const { me } = useAuth();
  if (!me) return false;
  return me.roles.includes(required);
}
