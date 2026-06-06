package grpc

import (
	"context"
	"io"
	"log"
	"sync"

	"ai-call-pion/sfu"
	pb "ai-call-pion/grpc/proto" // This assumes the generated code is here
)

type Server struct {
	pb.UnimplementedSFUServiceServer
	mu       sync.RWMutex
	sessions map[string]*sfu.Session
}

func NewServer() *Server {
	return &Server{
		sessions: make(map[string]*sfu.Session),
	}
}

func (s *Server) CreateSession(ctx context.Context, req *pb.CreateSessionRequest) (*pb.CreateSessionResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	session := sfu.NewSession(req.SessionId)
	s.sessions[req.SessionId] = session

	return &pb.CreateSessionResponse{SessionId: req.SessionId}, nil
}

func (s *Server) ProcessOffer(ctx context.Context, req *pb.OfferRequest) (*pb.AnswerResponse, error) {
	s.mu.RLock()
	session, ok := s.sessions[req.SessionId]
	s.mu.RUnlock()

	if !ok {
		return nil, nil // TODO: return error
	}

	answer, err := session.ProcessOffer(req.Sdp)
	if err != nil {
		return nil, err
	}

	return &pb.AnswerResponse{Sdp: answer}, nil
}

func (s *Server) AddIceCandidate(ctx context.Context, req *pb.IceCandidateRequest) (*pb.Empty, error) {
	s.mu.RLock()
	session, ok := s.sessions[req.SessionId]
	s.mu.RUnlock()

	if ok {
		session.AddIceCandidate(req.CandidateJson)
	}
	return &pb.Empty{}, nil
}

func (s *Server) StreamAudioToPion(stream pb.SFUService_StreamAudioToPionServer) error {
	for {
		chunk, err := stream.Recv()
		if err == io.EOF {
			return stream.SendAndClose(&pb.Empty{})
		}
		if err != nil {
			return err
		}

		s.mu.RLock()
		session, ok := s.sessions[chunk.SessionId]
		s.mu.RUnlock()

		if ok {
			session.PlayAudio(chunk.PcmData)
		}
	}
}

func (s *Server) StreamAudioFromPion(req *pb.SessionID, stream pb.SFUService_StreamAudioFromPionServer) error {
	s.mu.RLock()
	session, ok := s.sessions[req.SessionId]
	s.mu.RUnlock()

	if !ok {
		return nil
	}

	pcmChan := session.GetAudioStream()
	for pcm := range pcmChan {
		err := stream.Send(&pb.AudioChunk{
			SessionId: req.SessionId,
			PcmData:   pcm,
			SampleRate: 16000,
		})
		if err != nil {
			return err
		}
	}
	return nil
}

func (s *Server) EndSession(ctx context.Context, req *pb.SessionID) (*pb.Empty, error) {
	s.mu.Lock()
	session, ok := s.sessions[req.SessionId]
	delete(s.sessions, req.SessionId)
	s.mu.Unlock()

	if ok {
		session.Close()
	}
	return &pb.Empty{}, nil
}
