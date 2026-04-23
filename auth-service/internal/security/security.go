package security

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

var (
	ErrExpired = errors.New("token expired")
	ErrInvalid = errors.New("invalid token")
)

type Claims struct {
	Email string `json:"email"`
	jwt.RegisteredClaims
}

type IssuedToken struct {
	AccessToken string
	ExpiresIn   int
}

type Issuer struct {
	Secret []byte
	TTL    time.Duration
}

// hs256Only pins the accepted algorithm at parse time; jwt/v5 then rejects
// header mismatches before calling the keyfunc, which removes the need for
// a manual method type assertion and closes the `alg=none` / RS-vs-HS
// confusion class of bugs.
var hs256Only = jwt.WithValidMethods([]string{jwt.SigningMethodHS256.Alg()})

func (i Issuer) Issue(userID, email string) (IssuedToken, error) {
	now := time.Now()
	claims := Claims{
		Email: email,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   userID,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(i.TTL)),
		},
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signed, err := tok.SignedString(i.Secret)
	if err != nil {
		return IssuedToken{}, err
	}
	return IssuedToken{AccessToken: signed, ExpiresIn: int(i.TTL.Seconds())}, nil
}

func (i Issuer) Decode(raw string) (*Claims, error) {
	parsed, err := jwt.ParseWithClaims(raw, &Claims{}, func(*jwt.Token) (any, error) {
		return i.Secret, nil
	}, hs256Only)
	if err != nil {
		if errors.Is(err, jwt.ErrTokenExpired) {
			return nil, ErrExpired
		}
		return nil, ErrInvalid
	}
	claims, ok := parsed.Claims.(*Claims)
	if !ok || !parsed.Valid {
		return nil, ErrInvalid
	}
	return claims, nil
}
