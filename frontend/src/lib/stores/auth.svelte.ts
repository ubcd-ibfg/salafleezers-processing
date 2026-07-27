// Bearer-token holder for shared-lab deployments (SFZ_AUTH_TOKEN, see
// web/auth.py). Previously api.ts never sent an Authorization header at
// all, so turning on the exact auth mode the README recommends for shared
// labs 401'd every request and bricked the GUI -- this is what makes that
// mode actually usable from the SPA.
//
// sessionStorage (not localStorage): the token shouldn't outlive the tab by
// default, and shouldn't sync across devices the way localStorage can via
// browser sync -- a deliberately narrower blast radius for a bearer secret.

const KEY = 'sfz.authToken'

class AuthStore {
  token = $state<string | null>(sessionStorage.getItem(KEY))
  /** Learned from GET /api/health at boot; drives whether to show the token prompt. */
  required = $state(false)

  setToken(value: string | null) {
    this.token = value && value.trim() ? value.trim() : null
    if (this.token) sessionStorage.setItem(KEY, this.token)
    else sessionStorage.removeItem(KEY)
  }
}

export const auth = new AuthStore()
