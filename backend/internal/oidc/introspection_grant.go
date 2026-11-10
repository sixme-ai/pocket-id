package oidc

import (
	"context"
	"errors"
	"log/slog"

	"github.com/pocket-id/fosite"
)

// introspectionValidation rechecks the current user and API grants before a stored token is reported active
// Permanent policy rejection also invalidates the persisted request so restored permissions cannot revive the token
// Infrastructure failures deny introspection without permanently destroying an otherwise valid grant
// The store resolves clients from the current database rather than trusting the issuance-time client snapshot
type introspectionValidation struct {
	store     *Store
	claims    *ClaimsService
	apiAccess APIAccessProvider
}

func (v introspectionValidation) active(ctx context.Context, requester fosite.Requester, issuer string) bool {
	if v.store == nil || v.claims == nil || requester == nil {
		return false
	}
	err := v.check(ctx, requester, issuer)
	if err == nil {
		return true
	}
	if isRevokedGrant(err) {
		if revokeErr := v.store.revokeRequestIDs(ctx, []string{requester.GetID()}); revokeErr != nil {
			slog.ErrorContext(ctx, "Failed to persist invalidated OAuth grant", "error", revokeErr)
		}
	}
	return false
}

func (v introspectionValidation) check(ctx context.Context, requester fosite.Requester, issuer string) error {
	client, ok := requester.GetClient().(Client)
	if !ok {
		return fosite.ErrInactiveToken
	}
	session, ok := requester.GetSession().(*Session)
	if !ok {
		return fosite.ErrInactiveToken
	}
	subjectType := SubjectTypeUser
	if session.Subject == "" || session.Subject == "client-"+client.GetID() {
		subjectType = SubjectTypeClient
	} else if err := v.claims.ValidateUserAccess(ctx, session.Subject, client); err != nil {
		return err
	}
	resource, err := introspectedGrantResource(client.GetID(), issuer, requester.GetGrantedAudience())
	if err != nil {
		return err
	}
	_, _, err = resolveResource(ctx, nil, v.apiAccess, client.GetID(), resource,
		requester.GetGrantedScopes(), subjectType)
	return err
}

// The issuer is an additional audience for identity endpoints, not a separate API grant
func introspectedGrantResource(clientID, issuer string, audiences fosite.Arguments) (string, error) {
	remaining := make(fosite.Arguments, 0, len(audiences))
	for _, audience := range audiences {
		if audience == issuer && len(audiences) > 1 {
			continue
		}
		remaining = append(remaining, audience)
	}
	return refreshGrantResource(clientID, remaining)
}

func isRevokedGrant(err error) bool {
	return errors.Is(err, fosite.ErrInvalidGrant) || errors.Is(err, fosite.ErrAccessDenied) ||
		errors.Is(err, fosite.ErrInvalidScope) || errors.Is(err, fosite.ErrInvalidTarget)
}
