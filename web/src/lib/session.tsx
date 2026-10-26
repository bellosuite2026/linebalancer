import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./supabase";
import { api } from "./api";
import type { Org } from "./types";

interface Ctx {
  session: Session | null; loading: boolean; recovery: boolean; clearRecovery: () => void;
  orgs: Org[]; orgsLoaded: boolean; orgsError: string; refreshOrgs: () => Promise<Org[]>;
  currentOrg: Org | null; setCurrentOrgId: (id: string) => void;
  isSuperAdmin: boolean;
}
const SessionCtx = createContext<Ctx>(null as unknown as Ctx);
export const useSession = () => useContext(SessionCtx);

const ORG_KEY = "tlb.currentOrg";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [recovery, setRecovery] = useState(false);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgsLoaded, setOrgsLoaded] = useState(false);
  const [orgsError, setOrgsError] = useState("");
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [currentId, setCurrentId] = useState<string>(() => localStorage.getItem(ORG_KEY) || "");

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setLoading(false); });
    const { data } = supabase.auth.onAuthStateChange((event, s) => {
      setSession(s);
      if (event === "PASSWORD_RECOVERY") setRecovery(true);
      if (event === "SIGNED_OUT") { setOrgs([]); setOrgsLoaded(false); setIsSuperAdmin(false); }
    });
    return () => data.subscription.unsubscribe();
  }, []);

  const refreshOrgs = useCallback(async () => {
    setOrgsError("");
    try {
      const me = await api<{ orgs: Org[]; is_super_admin?: boolean }>("/v1/me");
      setOrgs(me.orgs);
      setIsSuperAdmin(!!me.is_super_admin);
      setOrgsLoaded(true);
      return me.orgs;
    } catch (e) {
      setOrgsError((e as Error).message);
      setOrgsLoaded(true);
      return [];
    }
  }, []);

  const userId = session?.user.id;
  useEffect(() => { if (userId) refreshOrgs(); }, [userId, refreshOrgs]);

  const setCurrentOrgId = (id: string) => { localStorage.setItem(ORG_KEY, id); setCurrentId(id); };
  const currentOrg = orgs.find((o) => o.id === currentId) || orgs[0] || null;

  return (
    <SessionCtx.Provider value={{ session, loading, recovery, clearRecovery: () => setRecovery(false),
      orgs, orgsLoaded, orgsError, refreshOrgs, currentOrg, setCurrentOrgId, isSuperAdmin }}>
      {children}
    </SessionCtx.Provider>
  );
}

export const canWrite = (o: Org | null) => !!o && o.role !== "lecteur";
export const canManage = (o: Org | null) => !!o && ["owner", "admin", "methodes"].includes(o.role);
