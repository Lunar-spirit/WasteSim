import { useQuery } from '@tanstack/react-query'
import { fetchCurrentUser } from '../api/endpoints'
import { isAuthenticated } from '../api/client'

/** Shared across the app via React Query's cache — every caller gets the
 * same single request, not one per component. */
export function useCurrentUser() {
  const query = useQuery({
    queryKey: ['currentUser'],
    queryFn: fetchCurrentUser,
    enabled: isAuthenticated(),
    staleTime: 5 * 60 * 1000,
  })

  return {
    user: query.data,
    isLoading: query.isLoading,
    isAdmin: query.data?.role === 'ADMIN',
    isViewer: query.data?.role === 'VIEWER',
  }
}
