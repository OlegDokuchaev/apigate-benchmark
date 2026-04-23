package users

import (
	"errors"
	"sync"

	"github.com/google/uuid"
	"golang.org/x/crypto/bcrypt"
)

var (
	ErrEmailTaken         = errors.New("email already registered")
	ErrInvalidCredentials = errors.New("invalid credentials")
)

type User struct {
	ID           string
	Email        string
	PasswordHash []byte
}

type Store struct {
	mu      sync.RWMutex
	byEmail map[string]*User
}

func NewStore() *Store {
	return &Store{byEmail: make(map[string]*User)}
}

// Create hashes the password before taking the write lock so concurrent
// registrations don't serialize on bcrypt. A duplicate email therefore
// wastes one hash, but registration is rare compared to login.
func (s *Store) Create(email, password string) (*User, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return nil, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.byEmail[email]; ok {
		return nil, ErrEmailTaken
	}
	u := &User{ID: uuid.NewString(), Email: email, PasswordHash: hash}
	s.byEmail[email] = u
	return u, nil
}

// Authenticate looks up the user under a read lock, then runs bcrypt
// without holding it — otherwise every concurrent /login would serialize
// on a single ~50ms hash comparison. Safe because User is immutable once
// inserted and there is no delete path.
func (s *Store) Authenticate(email, password string) (*User, error) {
	s.mu.RLock()
	u, ok := s.byEmail[email]
	s.mu.RUnlock()
	if !ok {
		return nil, ErrInvalidCredentials
	}
	if err := bcrypt.CompareHashAndPassword(u.PasswordHash, []byte(password)); err != nil {
		return nil, ErrInvalidCredentials
	}
	return u, nil
}
