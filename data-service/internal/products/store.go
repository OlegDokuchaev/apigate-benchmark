package products

import "strings"

type Product struct {
	ID       string `json:"id"`
	OwnerID  string `json:"owner_id"`
	Name     string `json:"name"`
	Price    int    `json:"price"`
	Category string `json:"category"`
}

// noProducts is returned instead of a nil slice so that JSON marshals as
// `[]` rather than `null` for empty results.
var noProducts = []Product{}

type Store struct {
	products []Product
	// Pre-computed per process start — the catalogue is immutable.
	ownerIndex map[string][]Product
	lowerNames []string
}

func NewStore() *Store {
	ps := seed()
	idx := make(map[string][]Product, len(ps))
	lower := make([]string, len(ps))
	for i, p := range ps {
		idx[p.OwnerID] = append(idx[p.OwnerID], p)
		lower[i] = strings.ToLower(p.Name)
	}
	return &Store{products: ps, ownerIndex: idx, lowerNames: lower}
}

func seed() []Product {
	return []Product{
		{ID: "p1", OwnerID: "u1", Name: "Blue pen", Price: 200, Category: "office"},
		{ID: "p2", OwnerID: "u1", Name: "Notebook A5", Price: 500, Category: "office"},
		{ID: "p3", OwnerID: "u1", Name: "Paper clips", Price: 50, Category: "office"},
		{ID: "p4", OwnerID: "u2", Name: "Ceramic mug", Price: 800, Category: "kitchen"},
		{ID: "p5", OwnerID: "u2", Name: "Tea spoon", Price: 100, Category: "kitchen"},
		{ID: "p6", OwnerID: "u3", Name: "Desk lamp", Price: 3000, Category: "home"},
		{ID: "p7", OwnerID: "u3", Name: "Floor mat", Price: 1500, Category: "home"},
	}
}

func (s *Store) All() []Product {
	return s.products
}

// ByOwner reads from a pre-built index. The returned slice is shared —
// handlers only marshal it, never mutate.
func (s *Store) ByOwner(ownerID string) []Product {
	if ps, ok := s.ownerIndex[ownerID]; ok {
		return ps
	}
	return noProducts
}

type SearchFilter struct {
	Category *string
	MaxPrice *int
}

func (s *Store) Search(f SearchFilter) []Product {
	out := make([]Product, 0, len(s.products))
	for _, p := range s.products {
		if f.Category != nil && p.Category != *f.Category {
			continue
		}
		if f.MaxPrice != nil && p.Price > *f.MaxPrice {
			continue
		}
		out = append(out, p)
	}
	return out
}

type LookupQuery struct {
	Query string
	Limit int
}

// Lookup matches against lowercased names from s.lowerNames, avoiding the
// per-product strings.ToLower allocation the naïve version did on every call.
func (s *Store) Lookup(q LookupQuery) []Product {
	if q.Query == "" {
		if q.Limit > 0 && q.Limit < len(s.products) {
			return s.products[:q.Limit]
		}
		return s.products
	}
	needle := strings.ToLower(q.Query)
	capHint := len(s.products)
	if q.Limit > 0 && q.Limit < capHint {
		capHint = q.Limit
	}
	out := make([]Product, 0, capHint)
	for i, p := range s.products {
		if !strings.Contains(s.lowerNames[i], needle) {
			continue
		}
		out = append(out, p)
		if q.Limit > 0 && len(out) >= q.Limit {
			break
		}
	}
	return out
}
