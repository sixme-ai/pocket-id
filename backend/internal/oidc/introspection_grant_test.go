package oidc

import (
	"testing"

	"github.com/pocket-id/fosite"
	"github.com/stretchr/testify/require"

	"github.com/pocket-id/pocket-id/backend/internal/appconfig"
	"github.com/pocket-id/pocket-id/backend/internal/model"
	testutils "github.com/pocket-id/pocket-id/backend/internal/utils/testing"
)

func TestIntrospectionPermanentlyRevokesAccessAfterGroupRemoval(t *testing.T) {
	db := testutils.NewDatabaseForTest(t)
	const clientID, userID = "group-client", "group-user"
	group := model.UserGroup{Base: model.Base{ID: "allowed-group"}, Name: "allowed"}
	user := model.User{Base: model.Base{ID: userID}, Username: "group-user"}
	client := model.OidcClient{Base: model.Base{ID: clientID}, Name: "Group Client", IsGroupRestricted: true}
	require.NoError(t, db.Create(&group).Error)
	require.NoError(t, db.Create(&user).Error)
	require.NoError(t, db.Create(&client).Error)
	require.NoError(t, db.Model(&user).Association("UserGroups").Append(&group))
	require.NoError(t, db.Model(&client).Association("AllowedUserGroups").Append(&group))

	store := NewStore(db, nil).WithIssuer("https://issuer.example.com")
	requester := newTestRequester("group-request", clientID, userID, "")
	requester.(*fosite.Request).GrantedAudience = fosite.Arguments{clientID}
	require.NoError(t, store.CreateAccessTokenSession(t.Context(), "group-access", requester))
	stored, err := store.GetAccessTokenSession(t.Context(), "group-access", nil)
	require.NoError(t, err)
	validation := introspectionValidation{
		store:  store,
		claims: newClaimsService(db, nil, "https://issuer.example.com", nil, appconfig.StaticResolver{}),
	}
	require.True(t, validation.active(t.Context(), stored, "https://issuer.example.com"))
	require.NoError(t, db.Model(&user).Association("UserGroups").Clear())
	require.False(t, validation.active(t.Context(), stored, "https://issuer.example.com"))
	require.NoError(t, db.Model(&user).Association("UserGroups").Append(&group))
	_, err = store.GetAccessTokenSession(t.Context(), "group-access", nil)
	require.ErrorIs(t, err, fosite.ErrNotFound)
}
