import { useEffect, useState } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { isAllowedAdminEmail } from '@/lib/auth';
import { Loader2 } from 'lucide-react';

export default function ProtectedRoute() {
  const { authenticated, loading, localBypass, signOut, user } = useAuth();
  const [revokingAccess, setRevokingAccess] = useState(false);
  const isAuthorized = isAllowedAdminEmail(user?.email);

  useEffect(() => {
    if (localBypass) {
      return;
    }

    if (!authenticated || isAuthorized) {
      return;
    }

    setRevokingAccess(true);
    void signOut().finally(() => {
      setRevokingAccess(false);
    });
  }, [authenticated, isAuthorized, signOut]);

  if (loading || revokingAccess) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
      </div>
    );
  }

  if (!authenticated && !localBypass) {
    return <Navigate to="/login" replace />;
  }

  if (!isAuthorized && !localBypass) {
    return <Navigate to="/login?reason=unauthorized" replace />;
  }

  return <Outlet />;
}
