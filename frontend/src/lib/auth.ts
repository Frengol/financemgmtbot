const configuredAdminEmails = (import.meta.env.VITE_ALLOWED_ADMIN_EMAILS || "")
  .split(",")
  .map((email) => email.trim().toLowerCase())
  .filter(Boolean);

export function isAllowedAdminEmail(email?: string | null) {
  if (configuredAdminEmails.length === 0) {
    return true;
  }

  return !!email && configuredAdminEmails.includes(email.toLowerCase());
}
